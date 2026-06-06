import io
from datetime import datetime, date
import pandas as pd
import streamlit as st

try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None
    Credentials = None

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
except Exception:
    canvas = None

# =========================
# 基本設定
# =========================
st.set_page_config(
    page_title="ネイル利益管理",
    page_icon="💅",
    layout="wide",
    initial_sidebar_state="collapsed",
)

DEFAULT_COURSES = [
    {"コース名": "ベーシックプラン", "料金": 60000},
    {"コース名": "アートプラン", "料金": 95000},
    {"コース名": "検定コース", "料金": 60000},
]
PURCHASE_SOURCES = ["TAT", "SHEIN", "楽天", "Amazon", "100均", "その他"]
BUYERS = ["阪口", "前山", "その他"]
DISCOUNT_OPTIONS = list(range(0, 101, 5))
TAX_RATE = 0.10


PDF_DEFAULT_COLUMNS = {
    "sales": ["日付", "期生", "生徒名", "コース", "支払い方法", "金額"],
    "expenses": ["日付", "商品名", "購入元", "金額", "購入者"],
    "tool_purchases": ["日付", "商品名", "購入元", "入力区分", "入力金額", "割引率", "割引額", "税抜価格", "消費税", "金額", "購入者"],
    "tool_sales": ["日付", "期生", "名前", "道具代"],
}
PDF_AMOUNT_COLUMNS = {
    "sales": ["日付", "金額"],
    "expenses": ["日付", "金額"],
    "tool_purchases": ["日付", "税抜価格", "消費税", "金額"],
    "tool_sales": ["日付", "道具代"],
}
MONEY_COLUMNS = {"金額", "道具代", "入力金額", "割引額", "税抜価格", "消費税", "料金"}

HEADERS = {
    "sales": ["id", "登録日時", "日付", "期生", "生徒名", "コース", "支払い方法", "金額"],
    "expenses": ["id", "登録日時", "日付", "商品名", "購入元", "金額", "購入者"],
    "tool_purchases": ["id", "登録日時", "日付", "商品名", "購入元", "入力区分", "入力金額", "割引率", "割引額", "税抜価格", "消費税", "金額", "購入者"],
    "tool_sales": ["id", "登録日時", "日付", "期生", "名前", "道具代"],
    "settings": ["設定種別", "コース名", "料金"],
}

st.markdown(
    """
<style>
.stApp{background:linear-gradient(135deg,#fff7fb 0%,#fff1f7 48%,#f8f3ff 100%)}
.block-container{max-width:1050px;padding-top:1rem;padding-bottom:5rem}
.main-title{font-size:2rem;font-weight:800;color:#56314e;margin-bottom:.1rem}
.sub-title{color:#8b6d84;margin-bottom:1rem}
.card{background:rgba(255,255,255,.88);border:1px solid rgba(255,255,255,.9);box-shadow:0 12px 32px rgba(169,116,151,.12);border-radius:22px;padding:18px;margin-bottom:16px}
div[data-testid="stMetric"]{background:rgba(255,255,255,.9);border-radius:18px;padding:12px 14px;box-shadow:0 8px 22px rgba(169,116,151,.10)}
.stButton>button,.stDownloadButton>button{width:100%;border-radius:15px;min-height:46px;font-weight:700}
.stTextInput input,.stNumberInput input,div[data-baseweb="select"]>div,textarea{border-radius:13px!important}
header[data-testid="stHeader"]{visibility:hidden;height:0}
#MainMenu,footer{visibility:hidden}
.small-note{color:#8b6d84;font-size:.9rem}
@media(max-width:768px){
.block-container{padding-left:.75rem;padding-right:.75rem;padding-top:.6rem}.main-title{font-size:1.55rem}.sub-title{font-size:.88rem}.card{border-radius:18px;padding:14px 12px}
div[data-testid="column"]{width:100%!important;flex:1 1 100%!important}
}
</style>
""",
    unsafe_allow_html=True,
)

# =========================
# 共通関数
# =========================
def yen(v):
    try:
        return f"¥{int(v):,}"
    except Exception:
        return "¥0"


def now_text():
    # 24時間表記
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def to_int(v):
    try:
        return int(float(str(v).replace(",", "").replace("¥", "")))
    except Exception:
        return 0


def normalize_id(v):
    try:
        return str(int(float(v)))
    except Exception:
        return str(v)


def sum_amount(records, key):
    return sum(to_int(r.get(key, 0)) for r in records)


def calc_tool_purchase(input_mode, input_amount, discount_rate):
    """道具購入の金額計算。
    入力金額に割引を反映し、最終的な税込金額を「金額」として扱う。
    """
    base = to_int(input_amount)
    discount_rate = to_int(discount_rate)
    discount_multiplier = max(0, 100 - discount_rate) / 100

    if input_mode == "税込価格で入力":
        original_tax_included = base
        final_tax_included = int(round(original_tax_included * discount_multiplier))
        final_tax_excluded = int(round(final_tax_included / (1 + TAX_RATE)))
        tax_amount = final_tax_included - final_tax_excluded
        discount_amount = original_tax_included - final_tax_included
    else:
        original_tax_excluded = base
        final_tax_excluded = int(round(original_tax_excluded * discount_multiplier))
        tax_amount = int(round(final_tax_excluded * TAX_RATE))
        final_tax_included = final_tax_excluded + tax_amount
        discount_amount = original_tax_excluded - final_tax_excluded

    return {
        "入力区分": input_mode,
        "入力金額": base,
        "割引率": discount_rate,
        "割引額": discount_amount,
        "税抜価格": final_tax_excluded,
        "消費税": tax_amount,
        "金額": final_tax_included,
    }


def show_table(records, hidden_cols=None):
    hidden_cols = hidden_cols or []
    if not records:
        st.info("まだ登録データがありません。")
        return
    df = pd.DataFrame(records)
    for col in hidden_cols:
        if col in df.columns:
            df = df.drop(columns=[col])
    st.dataframe(df, use_container_width=True, hide_index=True)


def show_table_with_total(records, amount_key, total_label, hidden_cols=None):
    """登録済み表と、その下の合計金額をまとめて表示する。"""
    show_table(records, hidden_cols=hidden_cols)
    total = sum_amount(records, amount_key) if records else 0
    st.markdown(
        f"<div style='text-align:right;font-weight:800;font-size:1.05rem;color:#56314e;margin-top:.5rem;'>"
        f"{total_label}：{yen(total)}"
        f"</div>",
        unsafe_allow_html=True,
    )


def next_id(records):
    if not records:
        return 1
    ids = [to_int(r.get("id", 0)) for r in records]
    return max(ids) + 1 if ids else 1


def get_spreadsheet():
    if gspread is None or Credentials is None:
        return None
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"], scopes=scopes
        )
        client = gspread.authorize(creds)
        return client.open_by_key(st.secrets["spreadsheet"]["key"])
    except Exception:
        return None


def ensure_ws(spreadsheet, name, headers):
    try:
        ws = spreadsheet.worksheet(name)
    except Exception:
        ws = spreadsheet.add_worksheet(title=name, rows=1000, cols=max(len(headers), 10))

    vals = ws.get_all_values()
    if not vals:
        ws.append_row(headers)
    elif vals[0] != headers:
        # 既存データがある場合も、先頭行だけ最新ヘッダーへ更新
        ws.update("A1", [headers])
    return ws


def save_record(sheet_name, row):
    ss = get_spreadsheet()
    if ss is None:
        return "Googleスプレッドシート未設定のため、この画面内だけに保存しました。"
    try:
        headers = HEADERS[sheet_name]
        ws = ensure_ws(ss, sheet_name, headers)
        ws.append_row([row.get(h, "") for h in headers], value_input_option="USER_ENTERED")
        return "Googleスプレッドシートに保存しました。"
    except Exception as e:
        return f"スプレッドシート保存に失敗しました：{e}"


def load_sheet(sheet_name):
    ss = get_spreadsheet()
    if ss is None:
        return []
    try:
        headers = HEADERS[sheet_name]
        ws = ensure_ws(ss, sheet_name, headers)
        records = ws.get_all_records()
        fixed = []
        changed = False
        for i, r in enumerate(records, start=1):
            row = {h: r.get(h, "") for h in headers}
            if not row.get("id") and "id" in headers:
                row["id"] = i
                changed = True
            fixed.append(row)
        if changed:
            rewrite_sheet(sheet_name, fixed)
        return fixed
    except Exception:
        return []


def find_row_number(ws, target_id):
    values = ws.get_all_values()
    if not values:
        return None
    headers = values[0]
    if "id" not in headers:
        return None
    id_idx = headers.index("id")
    target_id = normalize_id(target_id)
    for row_no, row in enumerate(values[1:], start=2):
        if len(row) > id_idx and normalize_id(row[id_idx]) == target_id:
            return row_no
    return None


def update_record(sheet_name, target_id, row):
    ss = get_spreadsheet()
    if ss is None:
        return "Googleスプレッドシート未設定のため、画面上のデータだけ更新しました。"
    try:
        headers = HEADERS[sheet_name]
        ws = ensure_ws(ss, sheet_name, headers)
        row_no = find_row_number(ws, target_id)
        if row_no is None:
            return "対象データがスプレッドシートに見つかりませんでした。"
        ws.update(f"A{row_no}:{chr(64+len(headers))}{row_no}", [[row.get(h, "") for h in headers]])
        return "Googleスプレッドシートを更新しました。"
    except Exception as e:
        return f"スプレッドシート更新に失敗しました：{e}"


def delete_record(sheet_name, target_id):
    ss = get_spreadsheet()
    if ss is None:
        return "Googleスプレッドシート未設定のため、画面上のデータだけ削除しました。"
    try:
        ws = ensure_ws(ss, sheet_name, HEADERS[sheet_name])
        row_no = find_row_number(ws, target_id)
        if row_no is None:
            return "対象データがスプレッドシートに見つかりませんでした。"
        ws.delete_rows(row_no)
        return "Googleスプレッドシートから削除しました。"
    except Exception as e:
        return f"スプレッドシート削除に失敗しました：{e}"


def rewrite_sheet(sheet_name, records):
    ss = get_spreadsheet()
    if ss is None:
        return "Googleスプレッドシート未設定のため、画面上だけに反映しました。"
    try:
        headers = HEADERS[sheet_name]
        ws = ensure_ws(ss, sheet_name, headers)
        ws.clear()
        values = [headers] + [[r.get(h, "") for h in headers] for r in records]
        ws.update("A1", values)
        return "Googleスプレッドシートに反映しました。"
    except Exception as e:
        return f"スプレッドシート反映に失敗しました：{e}"


def load_courses():
    ss = get_spreadsheet()
    if ss is None:
        return DEFAULT_COURSES.copy()
    try:
        ws = ensure_ws(ss, "settings", HEADERS["settings"])
        records = ws.get_all_records()
        courses = []
        for r in records:
            if r.get("設定種別") == "course" and str(r.get("コース名", "")).strip():
                courses.append({"コース名": str(r.get("コース名")).strip(), "料金": to_int(r.get("料金", 0))})
        return courses if courses else DEFAULT_COURSES.copy()
    except Exception:
        return DEFAULT_COURSES.copy()


def save_courses(courses):
    st.session_state.courses = courses
    ss = get_spreadsheet()
    if ss is None:
        return "Googleスプレッドシート未設定のため、画面上だけに反映しました。"
    try:
        ws = ensure_ws(ss, "settings", HEADERS["settings"])
        values = [HEADERS["settings"]]
        for c in courses:
            values.append(["course", c.get("コース名", ""), to_int(c.get("料金", 0))])
        ws.clear()
        ws.update("A1", values)
        return "コース設定をGoogleスプレッドシートに保存しました。"
    except Exception as e:
        return f"コース設定の保存に失敗しました：{e}"


def load_all():
    for key in ["sales", "expenses", "tool_purchases", "tool_sales"]:
        data = load_sheet(key)
        if data:
            st.session_state[key] = data
    st.session_state.courses = load_courses()


def totals():
    sales_total = sum_amount(st.session_state.sales, "金額")
    expenses_total = sum_amount(st.session_state.expenses, "金額")
    purchase_total = sum_amount(st.session_state.tool_purchases, "金額")
    tool_sales_total = sum_amount(st.session_state.tool_sales, "道具代")
    school_profit = sales_total - expenses_total
    tool_profit = tool_sales_total - purchase_total
    total_profit = school_profit + tool_profit
    return {
        "sales_total": sales_total,
        "expenses_total": expenses_total,
        "purchase_total": purchase_total,
        "tool_sales_total": tool_sales_total,
        "school_profit": school_profit,
        "tool_profit": tool_profit,
        "total_profit": total_profit,
        "tenant": int(total_profit * 0.2),
        "sakaguchi": int(total_profit * 0.2),
        "maeyama": int(total_profit * 0.6),
    }

# =========================
# PDF
# =========================
def _pdf_text(text, max_chars=16):
    text = "" if text is None else str(text)
    text = text.replace("\n", " ")
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def _draw_report_header(c, title, subtitle=None):
    c.setFont("HeiseiKakuGo-W5", 16)
    c.drawString(35, 805, title)
    c.setFont("HeiseiKakuGo-W5", 9)
    c.drawString(35, 787, f"作成日時：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if subtitle:
        c.drawString(35, 772, subtitle)
        y = 758
    else:
        y = 770
    c.line(35, y, 560, y)
    return y - 18


def _draw_table_header(c, x, y, columns, widths):
    c.setFont("HeiseiKakuGo-W5", 8)
    c.setFillGray(0.92)
    c.rect(x, y - 16, sum(widths), 16, stroke=1, fill=1)
    c.setFillGray(0)
    current_x = x
    for col, w in zip(columns, widths):
        c.rect(current_x, y - 16, w, 16, stroke=1, fill=0)
        c.drawString(current_x + 3, y - 11, _pdf_text(col, max(4, int(w / 6))))
        current_x += w
    return y - 16


def _draw_table_row(c, x, y, values, widths, font_size=7.2):
    c.setFont("HeiseiKakuGo-W5", font_size)
    row_h = 15
    current_x = x
    for val, w in zip(values, widths):
        c.rect(current_x, y - row_h, w, row_h, stroke=1, fill=0)
        c.drawString(current_x + 3, y - 10.5, _pdf_text(val, max(4, int(w / 5.6))))
        current_x += w
    return y - row_h


def _format_pdf_value(column, value):
    if column in MONEY_COLUMNS:
        return yen(value)
    if column == "割引率" and str(value) != "":
        return f"{to_int(value)}%"
    return value


def _auto_widths(columns, total_width=515):
    if not columns:
        return []
    min_w = 38
    base = max(min_w, int(total_width / len(columns)))
    widths = [base for _ in columns]
    diff = total_width - sum(widths)
    if widths:
        widths[-1] += diff
    return widths


def _draw_detail_table(c, title, records, columns, widths, y, amount_key=None):
    x = 35
    if y < 95:
        c.showPage()
        y = _draw_report_header(c, "ネイルスクール利益計算レポート", "①～④ 登録明細")
    c.setFont("HeiseiKakuGo-W5", 11)
    c.drawString(x, y, title)
    y -= 20
    if not records:
        c.setFont("HeiseiKakuGo-W5", 9)
        c.drawString(x + 8, y, "データなし")
        return y - 28

    y = _draw_table_header(c, x, y, columns, widths)
    for r in records:
        if y < 60:
            c.showPage()
            y = _draw_report_header(c, "ネイルスクール利益計算レポート", f"{title} 続き")
            y = _draw_table_header(c, x, y, columns, widths)
        values = [_format_pdf_value(col, r.get(col, "")) for col in columns]
        y = _draw_table_row(c, x, y, values, widths)

    if amount_key:
        if y < 50:
            c.showPage()
            y = _draw_report_header(c, "ネイルスクール利益計算レポート", f"{title} 合計")
        c.setFont("HeiseiKakuGo-W5", 9)
        c.drawRightString(x + sum(widths), y - 13, f"合計：{yen(sum_amount(records, amount_key))}")
        y -= 26
    return y - 6


def _draw_amount_only_table(c, y):
    t = totals()
    rows = [
        ["① 売上", len(st.session_state.sales), yen(t["sales_total"])],
        ["② 経費", len(st.session_state.expenses), yen(t["expenses_total"])],
        ["③ 道具購入", len(st.session_state.tool_purchases), yen(t["purchase_total"])],
        ["④ 道具販売", len(st.session_state.tool_sales), yen(t["tool_sales_total"])],
    ]
    columns = ["項目", "件数", "合計金額"]
    widths = [230, 90, 180]
    x = 45
    c.setFont("HeiseiKakuGo-W5", 11)
    c.drawString(x, y, "①～④ 金額のみ（個人情報非表示）")
    y -= 20
    y = _draw_table_header(c, x, y, columns, widths)
    for row in rows:
        y = _draw_table_row(c, x, y, row, widths, font_size=8.5)
    return y - 18


def _draw_summary_page(c):
    t = totals()
    y = _draw_report_header(c, "ネイルスクール利益計算レポート", "⑤ 集計・利益配分")
    x = 60
    rows = [
        ["売上合計", yen(t["sales_total"])],
        ["経費合計", yen(t["expenses_total"])],
        ["売上利益（売上合計－経費合計）", yen(t["school_profit"])],
        ["道具販売合計", yen(t["tool_sales_total"])],
        ["道具購入合計", yen(t["purchase_total"])],
        ["道具利益（道具販売合計－道具購入合計）", yen(t["tool_profit"])],
        ["総利益（売上利益＋道具利益）", yen(t["total_profit"])],
    ]
    columns = ["集計項目", "金額"]
    widths = [310, 160]
    c.setFont("HeiseiKakuGo-W5", 12)
    c.drawString(x, y, "⑤ 集計")
    y -= 22
    y = _draw_table_header(c, x, y, columns, widths)
    for row in rows:
        y = _draw_table_row(c, x, y, row, widths, font_size=8.5)

    y -= 30
    c.setFont("HeiseiKakuGo-W5", 12)
    c.drawString(x, y, "利益配分")
    y -= 22
    rows = [
        ["テナント賃料", "20%", yen(t["tenant"])],
        ["阪口", "20%", yen(t["sakaguchi"])],
        ["前山", "60%", yen(t["maeyama"])],
    ]
    columns = ["配分先", "割合", "金額"]
    widths = [220, 90, 160]
    y = _draw_table_header(c, x, y, columns, widths)
    for row in rows:
        y = _draw_table_row(c, x, y, row, widths, font_size=8.5)


def build_pdf(amount_only=False, selected_columns=None):
    """①～④は表形式、⑤集計は必ず別ページに分けてPDFを作成する。
    selected_columnsで①～④それぞれPDFに出す列を選択できる。
    """
    if canvas is None:
        return None
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    selected_columns = selected_columns or PDF_DEFAULT_COLUMNS
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    y = _draw_report_header(
        c,
        "ネイルスクール利益計算レポート",
        "①～④ 登録明細" if not amount_only else "①～④ 金額のみ（個人情報非表示）",
    )
    if amount_only:
        _draw_amount_only_table(c, y)
    else:
        sales_cols = selected_columns.get("sales") or ["金額"]
        expense_cols = selected_columns.get("expenses") or ["金額"]
        purchase_cols = selected_columns.get("tool_purchases") or ["金額"]
        tool_sale_cols = selected_columns.get("tool_sales") or ["道具代"]

        y = _draw_detail_table(c, "① 売上", st.session_state.sales, sales_cols, _auto_widths(sales_cols), y, "金額")
        y = _draw_detail_table(c, "② 経費", st.session_state.expenses, expense_cols, _auto_widths(expense_cols), y, "金額")
        y = _draw_detail_table(c, "③ 道具購入", st.session_state.tool_purchases, purchase_cols, _auto_widths(purchase_cols), y, "金額")
        y = _draw_detail_table(c, "④ 道具販売", st.session_state.tool_sales, tool_sale_cols, _auto_widths(tool_sale_cols), y, "道具代")

    c.showPage()
    _draw_summary_page(c)
    c.save()
    buf.seek(0)
    return buf.getvalue()

# =========================
# 初期化
# =========================
for k, v in {
    "sales": [],
    "expenses": [],
    "tool_purchases": [],
    "tool_sales": [],
    "courses": DEFAULT_COURSES.copy(),
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

if "loaded_once" not in st.session_state:
    load_all()
    st.session_state.loaded_once = True

# =========================
# 画面
# =========================
st.markdown('<div class="main-title">💅 ネイルスクール利益管理</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">売上・経費・道具購入・道具販売を入力して、利益と配分を確認</div>', unsafe_allow_html=True)

with st.sidebar:
    st.subheader("設定")
    if st.button("スプレッドシートから再読込"):
        load_all()
        st.success("読み込みました。")
        st.rerun()

    st.markdown("---")
    st.caption("コース名と料金を変更できます。")
    course_df = pd.DataFrame(st.session_state.courses)
    edited_df = st.data_editor(
        course_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "コース名": st.column_config.TextColumn("コース名", required=True),
            "料金": st.column_config.NumberColumn("料金", min_value=0, step=1000, required=True),
        },
        key="course_editor",
    )
    if st.button("コース設定を保存"):
        courses = []
        for _, r in edited_df.iterrows():
            name = str(r.get("コース名", "")).strip()
            price = to_int(r.get("料金", 0))
            if name:
                courses.append({"コース名": name, "料金": price})
        if not courses:
            st.error("コースを1つ以上登録してください。")
        else:
            msg = save_courses(courses)
            st.success(msg)
            st.rerun()

    st.caption("スプレッドシート設定前でも画面上で試せます。")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["① 売上", "② 経費", "③ 道具購入", "④ 道具販売", "⑤ 集計・出力"])

# =========================
# ① 売上
# =========================
with tab1:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("① 売上")
    course_names = [c["コース名"] for c in st.session_state.courses]
    course_price = {c["コース名"]: to_int(c["料金"]) for c in st.session_state.courses}
    with st.form("sales_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        sale_date = c1.date_input("日付", value=date.today(), key="sale_date")
        grade_no = c1.number_input("期生番号", min_value=1, max_value=999, value=1, step=1, key="sale_grade_no")
        c1.caption(f"表示：{grade_no}期生")
        student_name = c1.text_input("生徒名", placeholder="例：山田 花子")
        selected_courses = c2.multiselect("コース選択", course_names)
        payment_method = c2.text_input("支払い方法", placeholder="例：現金、PayPay、振込、カード")
        amount = sum(course_price.get(x, 0) for x in selected_courses)
        c2.metric("コース合計", yen(amount))
        submit = st.form_submit_button("売上を登録する")
    if submit:
        if not student_name.strip():
            st.error("生徒名を入力してください。")
        elif not selected_courses:
            st.error("コースを1つ以上選択してください。")
        else:
            row = {
                "id": next_id(st.session_state.sales),
                "登録日時": now_text(),
                "日付": sale_date.strftime("%Y-%m-%d"),
                "期生": f"{int(grade_no)}期生",
                "生徒名": student_name.strip(),
                "コース": "、".join(selected_courses),
                "支払い方法": payment_method.strip(),
                "金額": amount,
            }
            st.session_state.sales.append(row)
            st.success(save_record("sales", row))
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("**登録済み売上**")
    show_table_with_total(st.session_state.sales, "金額", "売上合計", hidden_cols=["id"])
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("**売上の編集・削除**")
    if not st.session_state.sales:
        st.info("編集できる売上データがありません。")
    else:
        labels = [f"{r.get('id')}｜{r.get('日付')}｜{r.get('期生')}｜{r.get('生徒名')}｜{yen(r.get('金額'))}" for r in st.session_state.sales]
        idx = st.selectbox("編集・削除する売上を選択", range(len(labels)), format_func=lambda i: labels[i], key="edit_sale_select")
        target = st.session_state.sales[idx]
        with st.form("edit_sale_form"):
            c1, c2 = st.columns(2)
            e_date = c1.date_input("日付", value=pd.to_datetime(target.get("日付", date.today())).date(), key="edit_sale_date")
            current_grade_no = to_int(str(target.get("期生", "1期生")).replace("期生", "")) or 1
            e_grade_no = c1.number_input("期生番号", min_value=1, max_value=999, value=current_grade_no, step=1, key="edit_sale_grade_no")
            c1.caption(f"表示：{e_grade_no}期生")
            e_name = c1.text_input("生徒名", value=str(target.get("生徒名", "")))
            current_courses = [x for x in str(target.get("コース", "")).split("、") if x in course_names]
            e_courses = c2.multiselect("コース選択", course_names, default=current_courses, key="edit_sale_courses")
            e_payment = c2.text_input("支払い方法", value=str(target.get("支払い方法", "")))
            e_amount = sum(course_price.get(x, 0) for x in e_courses)
            c2.metric("コース合計", yen(e_amount))
            update_btn = st.form_submit_button("売上を更新する")
            delete_btn = st.form_submit_button("売上を削除する")
        if update_btn:
            if not e_name.strip() or not e_courses:
                st.error("生徒名とコースを入力してください。")
            else:
                new_row = dict(target)
                new_row.update({"日付": e_date.strftime("%Y-%m-%d"), "期生": f"{int(e_grade_no)}期生", "生徒名": e_name.strip(), "コース": "、".join(e_courses), "支払い方法": e_payment.strip(), "金額": e_amount})
                st.session_state.sales[idx] = new_row
                st.success(update_record("sales", target.get("id"), new_row))
                st.rerun()
        if delete_btn:
            msg = delete_record("sales", target.get("id"))
            st.session_state.sales.pop(idx)
            st.success(msg)
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# =========================
# ② 経費
# =========================
with tab2:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("② 経費")
    with st.form("expense_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        d = c1.date_input("日付", value=date.today(), key="expense_date")
        name = c1.text_input("商品名", placeholder="例：家賃、消耗品、広告費")
        source = c1.selectbox("購入元", PURCHASE_SOURCES, key="expense_source")
        price = c2.number_input("金額", min_value=0, step=100, key="expense_price")
        buyer = c2.selectbox("購入者", BUYERS, key="expense_buyer")
        submit = st.form_submit_button("経費を登録する")
    if submit:
        if not name.strip():
            st.error("商品名を入力してください。")
        elif price <= 0:
            st.error("金額を入力してください。")
        else:
            row = {"id": next_id(st.session_state.expenses), "登録日時": now_text(), "日付": d.strftime("%Y-%m-%d"), "商品名": name.strip(), "購入元": source, "金額": int(price), "購入者": buyer}
            st.session_state.expenses.append(row)
            st.success(save_record("expenses", row))
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("**登録済み経費**")
    show_table_with_total(st.session_state.expenses, "金額", "経費合計", hidden_cols=["id"])
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("**経費の編集・削除**")
    if not st.session_state.expenses:
        st.info("編集できる経費データがありません。")
    else:
        labels = [f"{r.get('id')}｜{r.get('日付')}｜{r.get('商品名')}｜{yen(r.get('金額'))}" for r in st.session_state.expenses]
        idx = st.selectbox("編集・削除する経費を選択", range(len(labels)), format_func=lambda i: labels[i], key="edit_expense_select")
        target = st.session_state.expenses[idx]
        with st.form("edit_expense_form"):
            c1, c2 = st.columns(2)
            e_date = c1.date_input("日付", value=pd.to_datetime(target.get("日付", date.today())).date(), key="edit_expense_date")
            e_name = c1.text_input("商品名", value=str(target.get("商品名", "")))
            e_source = c1.selectbox("購入元", PURCHASE_SOURCES, index=PURCHASE_SOURCES.index(target.get("購入元")) if target.get("購入元") in PURCHASE_SOURCES else 0, key="edit_expense_source")
            e_price = c2.number_input("金額", min_value=0, step=100, value=to_int(target.get("金額", 0)), key="edit_expense_price")
            e_buyer = c2.selectbox("購入者", BUYERS, index=BUYERS.index(target.get("購入者")) if target.get("購入者") in BUYERS else 0, key="edit_expense_buyer")
            update_btn = st.form_submit_button("経費を更新する")
            delete_btn = st.form_submit_button("経費を削除する")
        if update_btn:
            if not e_name.strip() or e_price <= 0:
                st.error("商品名と金額を入力してください。")
            else:
                new_row = dict(target)
                new_row.update({"日付": e_date.strftime("%Y-%m-%d"), "商品名": e_name.strip(), "購入元": e_source, "金額": int(e_price), "購入者": e_buyer})
                st.session_state.expenses[idx] = new_row
                st.success(update_record("expenses", target.get("id"), new_row))
                st.rerun()
        if delete_btn:
            msg = delete_record("expenses", target.get("id"))
            st.session_state.expenses.pop(idx)
            st.success(msg)
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# =========================
# ③ 道具購入
# =========================
with tab3:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("③ 道具購入")
    st.caption("税込価格・税抜価格のどちらでも入力できます。割引率は5%刻みで選択できます。")
    with st.form("purchase_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        d = c1.date_input("日付", value=date.today(), key="purchase_date")
        name = c1.text_input("商品名", placeholder="例：ジェル、チップ、筆、TATまとめ買い")
        source = c1.selectbox("購入元", PURCHASE_SOURCES, key="purchase_source")
        buyer = c1.selectbox("購入者", BUYERS, key="purchase_buyer")

        input_mode = c2.radio("入力する金額の種類", ["税込価格で入力", "税抜価格で入力"], horizontal=True, key="purchase_input_mode")
        input_amount = c2.number_input("レシート金額・定価", min_value=0, step=100, key="purchase_input_amount")
        discount_rate = c2.selectbox("割引率", DISCOUNT_OPTIONS, index=0, format_func=lambda x: f"{x}%", key="purchase_discount_rate")
        calc = calc_tool_purchase(input_mode, input_amount, discount_rate)
        m1, m2, m3 = c2.columns(3)
        m1.metric("税込金額", yen(calc["金額"]))
        m2.metric("税抜金額", yen(calc["税抜価格"]))
        m3.metric("消費税", yen(calc["消費税"]))
        c2.caption(f"割引額：{yen(calc['割引額'])}")
        submit = st.form_submit_button("道具購入を登録する")
    if submit:
        if not name.strip():
            st.error("商品名を入力してください。")
        elif input_amount <= 0:
            st.error("金額を入力してください。")
        else:
            row = {
                "id": next_id(st.session_state.tool_purchases),
                "登録日時": now_text(),
                "日付": d.strftime("%Y-%m-%d"),
                "商品名": name.strip(),
                "購入元": source,
                "入力区分": calc["入力区分"],
                "入力金額": calc["入力金額"],
                "割引率": calc["割引率"],
                "割引額": calc["割引額"],
                "税抜価格": calc["税抜価格"],
                "消費税": calc["消費税"],
                "金額": calc["金額"],
                "購入者": buyer,
            }
            st.session_state.tool_purchases.append(row)
            st.success(save_record("tool_purchases", row))
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("**登録済み道具購入**")
    show_table_with_total(st.session_state.tool_purchases, "金額", "道具購入合計", hidden_cols=["id"])
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("**道具購入の編集・削除**")
    if not st.session_state.tool_purchases:
        st.info("編集できる道具購入データがありません。")
    else:
        labels = [f"{r.get('id')}｜{r.get('日付')}｜{r.get('商品名')}｜{yen(r.get('金額'))}" for r in st.session_state.tool_purchases]
        idx = st.selectbox("編集・削除する道具購入を選択", range(len(labels)), format_func=lambda i: labels[i], key="edit_purchase_select")
        target = st.session_state.tool_purchases[idx]
        with st.form("edit_purchase_form"):
            c1, c2 = st.columns(2)
            e_date = c1.date_input("日付", value=pd.to_datetime(target.get("日付", date.today())).date(), key="edit_purchase_date")
            e_name = c1.text_input("商品名", value=str(target.get("商品名", "")))
            e_source = c1.selectbox("購入元", PURCHASE_SOURCES, index=PURCHASE_SOURCES.index(target.get("購入元")) if target.get("購入元") in PURCHASE_SOURCES else 0, key="edit_purchase_source")
            e_buyer = c1.selectbox("購入者", BUYERS, index=BUYERS.index(target.get("購入者")) if target.get("購入者") in BUYERS else 0, key="edit_purchase_buyer")

            current_mode = str(target.get("入力区分", "税込価格で入力"))
            if current_mode not in ["税込価格で入力", "税抜価格で入力"]:
                current_mode = "税込価格で入力"
            e_input_mode = c2.radio("入力する金額の種類", ["税込価格で入力", "税抜価格で入力"], index=["税込価格で入力", "税抜価格で入力"].index(current_mode), horizontal=True, key="edit_purchase_input_mode")
            default_input_amount = to_int(target.get("入力金額", target.get("金額", 0)))
            e_input_amount = c2.number_input("レシート金額・定価", min_value=0, step=100, value=default_input_amount, key="edit_purchase_input_amount")
            current_discount = to_int(target.get("割引率", 0))
            if current_discount not in DISCOUNT_OPTIONS:
                current_discount = 0
            e_discount_rate = c2.selectbox("割引率", DISCOUNT_OPTIONS, index=DISCOUNT_OPTIONS.index(current_discount), format_func=lambda x: f"{x}%", key="edit_purchase_discount_rate")
            e_calc = calc_tool_purchase(e_input_mode, e_input_amount, e_discount_rate)
            m1, m2, m3 = c2.columns(3)
            m1.metric("税込金額", yen(e_calc["金額"]))
            m2.metric("税抜金額", yen(e_calc["税抜価格"]))
            m3.metric("消費税", yen(e_calc["消費税"]))
            c2.caption(f"割引額：{yen(e_calc['割引額'])}")
            update_btn = st.form_submit_button("道具購入を更新する")
            delete_btn = st.form_submit_button("道具購入を削除する")
        if update_btn:
            if not e_name.strip() or e_input_amount <= 0:
                st.error("商品名と金額を入力してください。")
            else:
                new_row = dict(target)
                new_row.update({
                    "日付": e_date.strftime("%Y-%m-%d"),
                    "商品名": e_name.strip(),
                    "購入元": e_source,
                    "入力区分": e_calc["入力区分"],
                    "入力金額": e_calc["入力金額"],
                    "割引率": e_calc["割引率"],
                    "割引額": e_calc["割引額"],
                    "税抜価格": e_calc["税抜価格"],
                    "消費税": e_calc["消費税"],
                    "金額": e_calc["金額"],
                    "購入者": e_buyer,
                })
                st.session_state.tool_purchases[idx] = new_row
                st.success(update_record("tool_purchases", target.get("id"), new_row))
                st.rerun()
        if delete_btn:
            msg = delete_record("tool_purchases", target.get("id"))
            st.session_state.tool_purchases.pop(idx)
            st.success(msg)
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# =========================
# ④ 道具販売
# =========================
with tab4:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("④ 道具販売")
    with st.form("tool_sale_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        d = c1.date_input("日付", value=date.today(), key="tool_sale_date")
        grade_no = c1.number_input("期生番号", min_value=1, max_value=999, value=1, step=1, key="tool_sale_grade_no")
        c1.caption(f"表示：{grade_no}期生")
        name = c1.text_input("名前", placeholder="例：山田 花子")
        price = c2.number_input("道具代", min_value=0, step=100, key="tool_sale_price")
        c2.metric("販売金額", yen(price))
        submit = st.form_submit_button("道具販売を登録する")
    if submit:
        if not name.strip():
            st.error("名前を入力してください。")
        elif price <= 0:
            st.error("道具代を入力してください。")
        else:
            row = {"id": next_id(st.session_state.tool_sales), "登録日時": now_text(), "日付": d.strftime("%Y-%m-%d"), "期生": f"{int(grade_no)}期生", "名前": name.strip(), "道具代": int(price)}
            st.session_state.tool_sales.append(row)
            st.success(save_record("tool_sales", row))
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("**登録済み道具販売**")
    show_table_with_total(st.session_state.tool_sales, "道具代", "道具販売合計", hidden_cols=["id"])
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("**道具販売の編集・削除**")
    if not st.session_state.tool_sales:
        st.info("編集できる道具販売データがありません。")
    else:
        labels = [f"{r.get('id')}｜{r.get('日付')}｜{r.get('期生')}｜{r.get('名前')}｜{yen(r.get('道具代'))}" for r in st.session_state.tool_sales]
        idx = st.selectbox("編集・削除する道具販売を選択", range(len(labels)), format_func=lambda i: labels[i], key="edit_tool_sale_select")
        target = st.session_state.tool_sales[idx]
        with st.form("edit_tool_sale_form"):
            c1, c2 = st.columns(2)
            e_date = c1.date_input("日付", value=pd.to_datetime(target.get("日付", date.today())).date(), key="edit_tool_sale_date")
            current_grade_no = to_int(str(target.get("期生", "1期生")).replace("期生", "")) or 1
            e_grade_no = c1.number_input("期生番号", min_value=1, max_value=999, value=current_grade_no, step=1, key="edit_tool_sale_grade_no")
            c1.caption(f"表示：{e_grade_no}期生")
            e_name = c1.text_input("名前", value=str(target.get("名前", "")))
            e_price = c2.number_input("道具代", min_value=0, step=100, value=to_int(target.get("道具代", 0)), key="edit_tool_sale_price")
            c2.metric("販売金額", yen(e_price))
            update_btn = st.form_submit_button("道具販売を更新する")
            delete_btn = st.form_submit_button("道具販売を削除する")
        if update_btn:
            if not e_name.strip() or e_price <= 0:
                st.error("名前と道具代を入力してください。")
            else:
                new_row = dict(target)
                new_row.update({"日付": e_date.strftime("%Y-%m-%d"), "期生": f"{int(e_grade_no)}期生", "名前": e_name.strip(), "道具代": int(e_price)})
                st.session_state.tool_sales[idx] = new_row
                st.success(update_record("tool_sales", target.get("id"), new_row))
                st.rerun()
        if delete_btn:
            msg = delete_record("tool_sales", target.get("id"))
            st.session_state.tool_sales.pop(idx)
            st.success(msg)
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# =========================
# ⑤ 集計・出力
# =========================
with tab5:
    t = totals()
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("⑤ 集計・出力")
    c1, c2, c3 = st.columns(3)
    c1.metric("売上合計", yen(t["sales_total"]))
    c2.metric("経費合計", yen(t["expenses_total"]))
    c3.metric("売上利益", yen(t["school_profit"]))
    c4, c5, c6 = st.columns(3)
    c4.metric("道具販売合計", yen(t["tool_sales_total"]))
    c5.metric("道具購入合計", yen(t["purchase_total"]))
    c6.metric("道具利益", yen(t["tool_profit"]))
    st.metric("総利益", yen(t["total_profit"]))
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("利益配分")
    p1, p2, p3 = st.columns(3)
    p1.metric("テナント賃料 20%", yen(t["tenant"]))
    p2.metric("阪口 20%", yen(t["sakaguchi"]))
    p3.metric("前山 60%", yen(t["maeyama"]))
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("出力・操作")
    pdf_mode = st.radio(
        "PDFの表示内容",
        ["詳細を表示", "金額のみ（個人情報非表示）"],
        horizontal=True,
        help="テナントの方へ共有する場合は、金額のみを選ぶと氏名・商品名などをPDFに出しません。詳細表示では、PDFに出す列を選択できます。",
    )
    amount_only = pdf_mode == "金額のみ（個人情報非表示）"

    selected_pdf_columns = PDF_AMOUNT_COLUMNS.copy() if amount_only else PDF_DEFAULT_COLUMNS.copy()
    if not amount_only:
        with st.expander("PDFに表示する項目を選択", expanded=True):
            st.caption("チェックした項目だけがPDFの①～④の表に反映されます。氏名や商品名を外すと、個人情報を隠したPDFにできます。")
            col_a, col_b = st.columns(2)
            selected_pdf_columns = {
                "sales": col_a.multiselect("① 売上に表示する項目", PDF_DEFAULT_COLUMNS["sales"], default=PDF_DEFAULT_COLUMNS["sales"]),
                "expenses": col_b.multiselect("② 経費に表示する項目", PDF_DEFAULT_COLUMNS["expenses"], default=PDF_DEFAULT_COLUMNS["expenses"]),
                "tool_purchases": col_a.multiselect("③ 道具購入に表示する項目", PDF_DEFAULT_COLUMNS["tool_purchases"], default=PDF_DEFAULT_COLUMNS["tool_purchases"]),
                "tool_sales": col_b.multiselect("④ 道具販売に表示する項目", PDF_DEFAULT_COLUMNS["tool_sales"], default=PDF_DEFAULT_COLUMNS["tool_sales"]),
            }
            if any(len(v) == 0 for v in selected_pdf_columns.values()):
                st.warning("項目が0個の表は、PDFでは金額項目だけを表示します。")
    b1, b2, b3 = st.columns(3)
    if b1.button("スプレッドシートから再読込", key="reload2"):
        load_all()
        st.success("再読込しました。")
        st.rerun()
    if b2.button("画面上の入力をクリア"):
        st.session_state.sales = []
        st.session_state.expenses = []
        st.session_state.tool_purchases = []
        st.session_state.tool_sales = []
        st.success("画面上の入力をクリアしました。スプレッドシートのデータは削除されません。")
    pdf_data = build_pdf(amount_only=amount_only, selected_columns=selected_pdf_columns)
    if pdf_data:
        suffix = "amount_only" if amount_only else "detail"
        b3.download_button(
            "レポートをダウンロード（①～④と⑤を別ページ）",
            data=pdf_data,
            file_name=f"nail_profit_report_{suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            mime="application/pdf",
        )
    else:
        b3.warning("PDF出力にはreportlabが必要です。")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("**計算式**")
    st.write(f"売上利益 = 売上合計 {yen(t['sales_total'])} - 経費合計 {yen(t['expenses_total'])} = {yen(t['school_profit'])}")
    st.write(f"道具利益 = 道具販売合計 {yen(t['tool_sales_total'])} - 道具購入合計 {yen(t['purchase_total'])} = {yen(t['tool_profit'])}")
    st.write(f"総利益 = 売上利益 {yen(t['school_profit'])} + 道具利益 {yen(t['tool_profit'])} = {yen(t['total_profit'])}")
    st.markdown('</div>', unsafe_allow_html=True)
