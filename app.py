import io
from datetime import datetime, date
import pandas as pd
import streamlit as st

try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
except Exception:
    canvas = None

st.set_page_config(page_title="ネイル利益管理", page_icon="💅", layout="wide", initial_sidebar_state="collapsed")

DEFAULT_COURSES = {"ベーシックプラン": 60000, "アートプラン": 95000, "検定コース": 60000}
GRADE_OPTIONS = [f"{i}期生" for i in range(1, 31)] + ["その他"]
PURCHASE_SOURCES = ["TAT", "SHEIN", "楽天", "Amazon", "100均", "その他"]
BUYERS = ["阪口", "前山", "その他"]

st.markdown("""
<style>
.stApp{background:linear-gradient(135deg,#fff7fb 0%,#fff1f7 48%,#f8f3ff 100%)}
.block-container{max-width:1050px;padding-top:1rem;padding-bottom:5rem}.main-title{font-size:2rem;font-weight:800;color:#56314e;margin-bottom:.1rem}.sub-title{color:#8b6d84;margin-bottom:1rem}.card{background:rgba(255,255,255,.88);border:1px solid rgba(255,255,255,.9);box-shadow:0 12px 32px rgba(169,116,151,.12);border-radius:22px;padding:18px;margin-bottom:16px}div[data-testid="stMetric"]{background:rgba(255,255,255,.9);border-radius:18px;padding:12px 14px;box-shadow:0 8px 22px rgba(169,116,151,.10)}.stButton>button,.stDownloadButton>button{width:100%;border-radius:15px;min-height:46px;font-weight:700}.stTextInput input,.stNumberInput input,div[data-baseweb="select"]>div,textarea{border-radius:13px!important}header[data-testid="stHeader"]{visibility:hidden;height:0}#MainMenu,footer{visibility:hidden}@media(max-width:768px){.block-container{padding-left:.75rem;padding-right:.75rem;padding-top:.6rem}.main-title{font-size:1.55rem}.sub-title{font-size:.88rem}.card{border-radius:18px;padding:14px 12px}div[data-testid="column"]{width:100%!important;flex:1 1 100%!important}}
</style>
""", unsafe_allow_html=True)

for k, v in {"sales": [], "expenses": [], "tool_purchases": [], "tool_sales": [], "courses": DEFAULT_COURSES.copy()}.items():
    if k not in st.session_state:
        st.session_state[k] = v

def yen(v):
    try: return f"¥{int(v):,}"
    except Exception: return "¥0"

def now_text(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def to_int(v):
    try: return int(float(str(v).replace(",", "").replace("¥", "")))
    except Exception: return 0

def sum_amount(records, key): return sum(to_int(r.get(key, 0)) for r in records)
def show_table(records):
    if not records: st.info("まだ登録データがありません。")
    else: st.dataframe(pd.DataFrame(records), use_container_width=True, hide_index=True)

def get_spreadsheet():
    if gspread is None: return None
    try:
        scopes=["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
        creds=Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
        client=gspread.authorize(creds)
        return client.open_by_key(st.secrets["spreadsheet"]["key"])
    except Exception:
        return None

def ensure_ws(spreadsheet, name, headers):
    try: ws = spreadsheet.worksheet(name)
    except Exception: ws = spreadsheet.add_worksheet(title=name, rows=1000, cols=max(len(headers), 10))
    vals = ws.get_all_values()
    if not vals: ws.append_row(headers)
    elif vals[0] != headers: ws.update("A1", [headers])
    return ws

def save_record(sheet_name, row):
    ss = get_spreadsheet()
    if ss is None:
        return "Googleスプレッドシート未設定のため、この画面内だけに保存しました。"
    try:
        headers = list(row.keys())
        ws = ensure_ws(ss, sheet_name, headers)
        ws.append_row(list(row.values()), value_input_option="USER_ENTERED")
        return "Googleスプレッドシートに保存しました。"
    except Exception as e:
        return f"スプレッドシート保存に失敗しました：{e}"

def load_sheet(sheet_name, headers):
    ss = get_spreadsheet()
    if ss is None: return []
    try:
        ws = ensure_ws(ss, sheet_name, headers)
        return ws.get_all_records()
    except Exception:
        return []

def load_all():
    data = load_sheet("sales", ["登録日時","日付","期生","生徒名","コース","支払い方法","金額"])
    if data: st.session_state.sales = data
    data = load_sheet("expenses", ["登録日時","日付","商品名","購入元","金額","購入者"])
    if data: st.session_state.expenses = data
    data = load_sheet("tool_purchases", ["登録日時","日付","商品名","購入元","金額","購入者"])
    if data: st.session_state.tool_purchases = data
    data = load_sheet("tool_sales", ["登録日時","日付","期生","名前","道具代"])
    if data: st.session_state.tool_sales = data

def totals():
    sales_total=sum_amount(st.session_state.sales,"金額")
    expenses_total=sum_amount(st.session_state.expenses,"金額")
    purchase_total=sum_amount(st.session_state.tool_purchases,"金額")
    tool_sales_total=sum_amount(st.session_state.tool_sales,"道具代")
    school_profit=sales_total-expenses_total
    tool_profit=tool_sales_total-purchase_total
    total_profit=school_profit+tool_profit
    return {"sales_total":sales_total,"expenses_total":expenses_total,"purchase_total":purchase_total,"tool_sales_total":tool_sales_total,"school_profit":school_profit,"tool_profit":tool_profit,"total_profit":total_profit,"tenant":int(total_profit*.2),"sakaguchi":int(total_profit*.2),"maeyama":int(total_profit*.6)}

def draw_records(c, title, records, headers, y):
    c.setFont("HeiseiKakuGo-W5", 12); c.drawString(40, y, title); y -= 18
    c.setFont("HeiseiKakuGo-W5", 8.5)
    if not records:
        c.drawString(48, y, "データなし"); return y - 22
    for i, r in enumerate(records, 1):
        if y < 70:
            c.showPage(); c.setFont("HeiseiKakuGo-W5", 8.5); y = 800
        line = f"{i}. " + " / ".join([f"{h}:{r.get(h,'')}" for h in headers])
        c.drawString(48, y, line[:105]); y -= 15
    return y - 8

def build_pdf():
    if canvas is None: return None
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    t = totals(); buf = io.BytesIO(); c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("HeiseiKakuGo-W5", 18); c.drawString(40, 805, "ネイルスクール利益計算レポート")
    c.setFont("HeiseiKakuGo-W5", 10); c.drawString(40, 785, f"作成日時：{datetime.now().strftime('%Y-%m-%d %H:%M')}"); c.line(40, 775, 555, 775)
    y = 750
    y = draw_records(c, "① 売上", st.session_state.sales, ["日付","期生","生徒名","コース","支払い方法","金額"], y)
    y = draw_records(c, "② 経費", st.session_state.expenses, ["日付","商品名","購入元","金額","購入者"], y)
    y = draw_records(c, "③ 道具購入", st.session_state.tool_purchases, ["日付","商品名","購入元","金額","購入者"], y)
    y = draw_records(c, "④ 道具販売", st.session_state.tool_sales, ["日付","期生","名前","道具代"], y)
    if y < 250: c.showPage(); y = 800
    c.setFont("HeiseiKakuGo-W5", 13); c.drawString(40, y, "⑤ 集計"); y -= 22
    c.setFont("HeiseiKakuGo-W5", 10)
    lines=[f"売上合計：{yen(t['sales_total'])}",f"経費合計：{yen(t['expenses_total'])}",f"売上利益：売上合計 - 経費合計 = {yen(t['school_profit'])}","",f"道具販売合計：{yen(t['tool_sales_total'])}",f"道具購入合計：{yen(t['purchase_total'])}",f"道具利益：道具販売合計 - 道具購入合計 = {yen(t['tool_profit'])}","",f"総利益：売上利益 + 道具利益 = {yen(t['total_profit'])}","","利益配分",f"テナント賃料 20%：{yen(t['tenant'])}",f"阪口 20%：{yen(t['sakaguchi'])}",f"前山 60%：{yen(t['maeyama'])}"]
    for line in lines:
        if y < 50: c.showPage(); c.setFont("HeiseiKakuGo-W5", 10); y = 800
        c.drawString(48, y, line); y -= 17
    c.save(); buf.seek(0); return buf.getvalue()

st.markdown('<div class="main-title">💅 ネイルスクール利益管理</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">売上・経費・道具購入・道具販売を入力して、利益と配分を確認</div>', unsafe_allow_html=True)

with st.sidebar:
    st.subheader("設定")
    if st.button("スプレッドシートから再読込"):
        load_all(); st.success("読み込みました。")
    st.caption("コース名と金額を変更できます。")
    new_courses = {}
    for i, (name, price) in enumerate(st.session_state.courses.items()):
        c1, c2 = st.columns([1.4, 1])
        edited_name = c1.text_input("コース名", value=name, key=f"course_name_{i}")
        edited_price = c2.number_input("金額", min_value=0, step=1000, value=int(price), key=f"course_price_{i}")
        if edited_name.strip(): new_courses[edited_name.strip()] = int(edited_price)
    if st.button("コース設定を反映"):
        st.session_state.courses = new_courses; st.success("反映しました。")
    st.caption("スプレッドシート設定前でも画面上で試せます。")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["① 売上", "② 経費", "③ 道具購入", "④ 道具販売", "⑤ 集計・出力"])

with tab1:
    st.markdown('<div class="card">', unsafe_allow_html=True); st.subheader("① 売上")
    with st.form("sales_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        sale_date = c1.date_input("日付", value=date.today(), key="sale_date")
        grade = c1.selectbox("期生", GRADE_OPTIONS, key="sale_grade")
        student_name = c1.text_input("生徒名", placeholder="例：山田 花子")
        selected_courses = c2.multiselect("コース選択", list(st.session_state.courses.keys()))
        payment_method = c2.text_input("支払い方法", placeholder="例：現金、PayPay、振込、カード")
        amount = sum(st.session_state.courses.get(x, 0) for x in selected_courses)
        c2.metric("コース合計", yen(amount))
        submit = st.form_submit_button("売上を登録する")
    if submit:
        if not student_name.strip(): st.error("生徒名を入力してください。")
        elif not selected_courses: st.error("コースを1つ以上選択してください。")
        else:
            row={"登録日時":now_text(),"日付":sale_date.strftime("%Y-%m-%d"),"期生":grade,"生徒名":student_name.strip(),"コース":"、".join(selected_courses),"支払い方法":payment_method.strip(),"金額":amount}
            st.session_state.sales.append(row); st.success(save_record("sales", row))
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="card">', unsafe_allow_html=True); st.markdown("**登録済み売上**"); show_table(st.session_state.sales); st.markdown('</div>', unsafe_allow_html=True)

with tab2:
    st.markdown('<div class="card">', unsafe_allow_html=True); st.subheader("② 経費")
    with st.form("expense_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        d = c1.date_input("日付", value=date.today(), key="expense_date")
        name = c1.text_input("商品名", placeholder="例：家賃、消耗品、広告費")
        source = c1.selectbox("購入元", PURCHASE_SOURCES, key="expense_source")
        price = c2.number_input("金額", min_value=0, step=100, key="expense_price")
        buyer = c2.selectbox("購入者", BUYERS, key="expense_buyer")
        submit = st.form_submit_button("経費を登録する")
    if submit:
        if not name.strip(): st.error("商品名を入力してください。")
        elif price <= 0: st.error("金額を入力してください。")
        else:
            row={"登録日時":now_text(),"日付":d.strftime("%Y-%m-%d"),"商品名":name.strip(),"購入元":source,"金額":int(price),"購入者":buyer}
            st.session_state.expenses.append(row); st.success(save_record("expenses", row))
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="card">', unsafe_allow_html=True); st.markdown("**登録済み経費**"); show_table(st.session_state.expenses); st.markdown('</div>', unsafe_allow_html=True)

with tab3:
    st.markdown('<div class="card">', unsafe_allow_html=True); st.subheader("③ 道具購入")
    with st.form("purchase_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        d = c1.date_input("日付", value=date.today(), key="purchase_date")
        name = c1.text_input("商品名", placeholder="例：ジェル、チップ、筆")
        source = c1.selectbox("購入元", PURCHASE_SOURCES, key="purchase_source")
        price = c2.number_input("金額", min_value=0, step=100, key="purchase_price")
        buyer = c2.selectbox("購入者", BUYERS, key="purchase_buyer")
        submit = st.form_submit_button("道具購入を登録する")
    if submit:
        if not name.strip(): st.error("商品名を入力してください。")
        elif price <= 0: st.error("金額を入力してください。")
        else:
            row={"登録日時":now_text(),"日付":d.strftime("%Y-%m-%d"),"商品名":name.strip(),"購入元":source,"金額":int(price),"購入者":buyer}
            st.session_state.tool_purchases.append(row); st.success(save_record("tool_purchases", row))
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="card">', unsafe_allow_html=True); st.markdown("**登録済み道具購入**"); show_table(st.session_state.tool_purchases); st.markdown('</div>', unsafe_allow_html=True)

with tab4:
    st.markdown('<div class="card">', unsafe_allow_html=True); st.subheader("④ 道具販売")
    with st.form("tool_sale_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        d = c1.date_input("日付", value=date.today(), key="tool_sale_date")
        grade = c1.selectbox("期生", GRADE_OPTIONS, key="tool_sale_grade")
        name = c1.text_input("名前", placeholder="例：山田 花子")
        price = c2.number_input("道具代", min_value=0, step=100, key="tool_sale_price")
        c2.metric("販売金額", yen(price))
        submit = st.form_submit_button("道具販売を登録する")
    if submit:
        if not name.strip(): st.error("名前を入力してください。")
        elif price <= 0: st.error("道具代を入力してください。")
        else:
            row={"登録日時":now_text(),"日付":d.strftime("%Y-%m-%d"),"期生":grade,"名前":name.strip(),"道具代":int(price)}
            st.session_state.tool_sales.append(row); st.success(save_record("tool_sales", row))
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="card">', unsafe_allow_html=True); st.markdown("**登録済み道具販売**"); show_table(st.session_state.tool_sales); st.markdown('</div>', unsafe_allow_html=True)

with tab5:
    t = totals()
    st.markdown('<div class="card">', unsafe_allow_html=True); st.subheader("⑤ 集計・出力")
    c1,c2,c3 = st.columns(3); c1.metric("売上合計", yen(t["sales_total"])); c2.metric("経費合計", yen(t["expenses_total"])); c3.metric("売上利益", yen(t["school_profit"]))
    c4,c5,c6 = st.columns(3); c4.metric("道具販売合計", yen(t["tool_sales_total"])); c5.metric("道具購入合計", yen(t["purchase_total"])); c6.metric("道具利益", yen(t["tool_profit"]))
    st.metric("総利益", yen(t["total_profit"])); st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="card">', unsafe_allow_html=True); st.subheader("利益配分")
    p1,p2,p3=st.columns(3); p1.metric("テナント賃料 20%", yen(t["tenant"])); p2.metric("阪口 20%", yen(t["sakaguchi"])); p3.metric("前山 60%", yen(t["maeyama"])); st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="card">', unsafe_allow_html=True)
    b1,b2,b3 = st.columns(3)
    if b1.button("スプレッドシートから再読込", key="reload2"):
        load_all(); st.success("再読込しました。")
    if b2.button("画面上の入力をクリア"):
        st.session_state.sales=[]; st.session_state.expenses=[]; st.session_state.tool_purchases=[]; st.session_state.tool_sales=[]; st.success("画面上の入力をクリアしました。")
    pdf_data = build_pdf()
    if pdf_data:
        b3.download_button("レポートをダウンロード", data=pdf_data, file_name=f"nail_profit_report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf", mime="application/pdf")
    else:
        b3.warning("PDF出力にはreportlabが必要です。")
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<div class="card">', unsafe_allow_html=True); st.markdown("**計算式**")
    st.write(f"売上利益 = 売上合計 {yen(t['sales_total'])} - 経費合計 {yen(t['expenses_total'])} = {yen(t['school_profit'])}")
    st.write(f"道具利益 = 道具販売合計 {yen(t['tool_sales_total'])} - 道具購入合計 {yen(t['purchase_total'])} = {yen(t['tool_profit'])}")
    st.write(f"総利益 = 売上利益 {yen(t['school_profit'])} + 道具利益 {yen(t['tool_profit'])} = {yen(t['total_profit'])}")
    st.markdown('</div>', unsafe_allow_html=True)
