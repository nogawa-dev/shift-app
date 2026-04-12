import os
import json
import jpholiday
import requests # 🌟 専用ライブラリの代わりにこれを使う！
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from threading import Timer
import webbrowser

app = Flask(__name__)
app.secret_key = 'super_secret_key_hiro'

# 🌟 Supabaseの接続設定（自分の鍵に書き換えてね！）
SUPABASE_URL = "https://giwuiizjwaolzsxcirrj.supabase.co"
SUPABASE_KEY = "sb_publishable_24HZKwZ6Kotr4IqF3nGeMg_T_Rjo8hM"

def get_headers():
    """DBと通信するための共通の鍵セット"""
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

def get_display_name():
    return session.get('last_name', 'ゲスト')

def load_valid_dates():
    """DBから募集中の日付リストを読み込む"""
    try:
        res = requests.get(f"{SUPABASE_URL}/rest/v1/settings?id=eq.1&select=valid_dates", headers=get_headers())
        if res.status_code == 200 and res.json():
            return json.loads(res.json()[0]['valid_dates'])
    except Exception as e:
        print(e)
    return []

# 🌟 追加：ログイン中のユーザーが自分のパスワードをサクッと変更する裏口（API）
@app.route('/change_password', methods=['POST'])
def change_password():
    if 'user_name' not in session: 
        return jsonify({"status": "error"}), 401
        
    new_password = request.json.get('new_password')
    username = session['user_name'] # 今ログインしている人のID
    
    if new_password:
        # Supabaseの自分のパスワードだけを上書き更新する
        requests.patch(f"{SUPABASE_URL}/rest/v1/users?username=eq.{username}", headers=get_headers(), json={'password': new_password})
        return jsonify({"status": "success"})
            
    return jsonify({"status": "error"}), 400

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # 🌟 DBからユーザーを検索
        res = requests.get(f"{SUPABASE_URL}/rest/v1/users?username=eq.{username}&select=*", headers=get_headers())
        if res.status_code == 200 and res.json():
            user = res.json()[0]
            if user['password'] == password:
                session['user_name'] = username
                session['role'] = user['role']
                session['last_name'] = user.get('last_name', '')
                
                if not session['last_name']:
                    return redirect(url_for('setup'))
                return redirect(url_for('index'))
                
        return render_template('login.html', error="IDかパスワードが違います")
    return render_template('login.html')

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if 'user_name' not in session: return redirect(url_for('login'))
    
    if request.method == 'POST':
        last_name = request.form.get('last_name')
        username = session['user_name']
        
        # 🌟 DBのカレンダー表示名（last_name）を更新
        requests.patch(f"{SUPABASE_URL}/rest/v1/users?username=eq.{username}", headers=get_headers(), json={'last_name': last_name})
        session['last_name'] = last_name
        
        return redirect(url_for('index'))
    return render_template('setup.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username')
        last_name = request.form.get('last_name')
        new_password = request.form.get('new_password')
        
        # 🌟 DBでIDと名字が一致するか確認
        res = requests.get(f"{SUPABASE_URL}/rest/v1/users?username=eq.{username}&last_name=eq.{last_name}&select=*", headers=get_headers())
        if res.status_code == 200 and res.json():
            requests.patch(f"{SUPABASE_URL}/rest/v1/users?username=eq.{username}", headers=get_headers(), json={'password': new_password})
            return render_template('forgot.html', success="パスワードをリセットしました！新しいパスワードでログインしてください。")
        else:
            return render_template('forgot.html', error="IDかカレンダー表示名が間違っています。")
            
    return render_template('forgot.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'user_name' not in session: return redirect(url_for('login'))
    if not session.get('last_name'): return redirect(url_for('setup'))
    
    valid_dates = load_valid_dates()
    return render_template('index.html', user_name=get_display_name(), role=session['role'], valid_dates=valid_dates)

@app.route('/calendar')
def calendar():
    if 'user_name' not in session: return redirect(url_for('login'))
    if not session.get('last_name'): return redirect(url_for('setup'))
    
    # 🌟 画面を表示するだけ（データは下のAPIで裏から渡す）
    return render_template('calendar.html', user_name=get_display_name(), role=session['role'])

@app.route('/api/shifts')
def api_shifts():
    if 'user_name' not in session: return jsonify([])
    
    # DBから全シフトを取得
    res = requests.get(f"{SUPABASE_URL}/rest/v1/shifts?select=*,users(last_name)", headers=get_headers())
    shifts = res.json() if res.status_code == 200 else []

    role = session.get('role')
    current_user = session.get('user_name')
    events = []

    for shift in shifts:
        status = shift.get('status', '未確定')
        shift_id = shift.get('id')
        display_name = shift['users']['last_name']
        time_slot = shift['time_slot'] # 例: "1. 7:30-8:30"
        display_time = time_slot.split('. ')[1] if '. ' in time_slot else time_slot
        event_title = f"{display_name} ({display_time})"
        shift_date = shift['shift_date']
        
        # 🌟 追加：時間帯の「先頭の番号（1, 2, 3...）」をソート用の整理番号として取り出す
        order_key = time_slot.split('.')[0] if '.' in time_slot else '99'
        
        # 🌟 変更：extendedProps の中に "orderId" として整理番号を追加！
        if status == '確定':
            events.append({
                "title": event_title, 
                "start": shift_date, 
                "backgroundColor": "#28a745", 
                "borderColor": "#28a745", 
                "extendedProps": {"status": "confirmed", "id": shift_id, "orderId": order_key}
            })
        elif role in ['owner', 'admin'] and status == '未確定':
            events.append({
                "title": "【未】" + event_title, 
                "start": shift_date, 
                "backgroundColor": "#ffc107", 
                "borderColor": "#ffc107", 
                "textColor": "#212529", 
                "extendedProps": {"status": "pending", "id": shift_id, "orderId": order_key}
            })
        elif role == 'user' and shift['username'] == current_user and status == '未確定':
            events.append({
                "title": "【提出中】" + display_time, 
                "start": shift_date, 
                "backgroundColor": "#e7f1ff", 
                "borderColor": "#007bff", 
                "textColor": "#007bff", 
                "extendedProps": {"status": "my_pending", "id": shift_id, "orderId": order_key}
            })
            
    return jsonify(events)

# 🌟 カレンダー上からの「確定」を受け取る処理
@app.route('/approve', methods=['POST'])
def approve_shift():
    if 'user_name' not in session or session.get('role') not in ['owner', 'admin']:
        return redirect(url_for('calendar'))
        
    shift_id = request.form.get('shift_id')
    if shift_id:
        # DBのステータスを「確定」に書き換える
        requests.patch(f"{SUPABASE_URL}/rest/v1/shifts?id=eq.{shift_id}", headers=get_headers(), json={'status': '確定'})
        
    return redirect(url_for('calendar'))

@app.route('/submit_bulk', methods=['POST'])
def submit_bulk():
    if 'user_name' not in session:
        return jsonify({"status": "error", "message": "未ログイン"}), 401
        
    data = request.json
    shifts_data = data.get('shifts', {})
    memo = data.get('memo', '')
    username = session['user_name']
    
    # 🌟 選ばれたシフトをDBに一括保存
    payload = []
    for date, slots in shifts_data.items():
        for slot in slots:
            payload.append({
                'username': username,
                'shift_date': date,
                'time_slot': slot,
                'memo': memo,
                'status': '未確定'
            })
            
    if payload:
        requests.post(f"{SUPABASE_URL}/rest/v1/shifts", headers=get_headers(), json=payload)
            
    return jsonify({"status": "success"})

@app.route('/register_users', methods=['GET', 'POST'])
def register_users():
    if 'user_name' not in session or session.get('role') != 'owner':
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        new_username = request.form.get('username')
        new_password = request.form.get('password')
        new_role = request.form.get('role')
        
        # 新規ユーザーをDBに登録
        res = requests.post(f"{SUPABASE_URL}/rest/v1/users", headers=get_headers(), json={
            'username': new_username, 
            'password': new_password, 
            'role': new_role,
            'last_name': ''
        })
        
        # 🌟 ここを追加！：ターミナルにエラーの理由を白状させる！
        print(f"★ユーザー登録テスト (送信ID: {new_username}):", res.status_code, res.text)
        
        # 画面に表示するために最新のユーザー一覧を取得
        users_res = requests.get(f"{SUPABASE_URL}/rest/v1/users?select=*", headers=get_headers())
        users_data = users_res.json() if users_res.status_code == 200 else []
        users_dict = { u['username']: {"pass": u['password'], "role": u['role'], "last_name": u.get('last_name', '')} for u in users_data }
        
        if res.status_code in [200, 201]:
            return render_template('register.html', success=f"ユーザー「{new_username}」を登録しました！", user_name=get_display_name(), role=session['role'], users=users_dict)
        else:
            return render_template('register.html', error="登録に失敗しました（詳細はターミナルを確認）", user_name=get_display_name(), role=session['role'], users=users_dict)
            
    # 通常アクセス時もユーザー一覧を取得して渡す
    users_res = requests.get(f"{SUPABASE_URL}/rest/v1/users?select=*", headers=get_headers())
    users_data = users_res.json() if users_res.status_code == 200 else []
    users_dict = { u['username']: {"pass": u['password'], "role": u['role'], "last_name": u.get('last_name', '')} for u in users_data }
            
    return render_template('register.html', user_name=get_display_name(), role=session['role'], users=users_dict)

@app.route('/settings', methods=['GET', 'POST'])
def shift_settings():
    if 'user_name' not in session or session.get('role') not in ['owner', 'admin']:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        start_str = request.form.get('start_date')
        end_str = request.form.get('end_date')
        
        if start_str and end_str:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d')
            valid_dates = []
            
            current = start_date
            while current <= end_date:
                if current.weekday() < 5 and not jpholiday.is_holiday(current.date()):
                    valid_dates.append(current.strftime('%Y-%m-%d'))
                current += timedelta(days=1)
                
            # 🌟 DBに募集期間を保存
            requests.patch(f"{SUPABASE_URL}/rest/v1/settings?id=eq.1", headers=get_headers(), json={'valid_dates': json.dumps(valid_dates)})
            
            return render_template('settings.html', success="募集期間を更新しました！", user_name=get_display_name(), role=session['role'], valid_dates=valid_dates)
            
    current_dates = load_valid_dates()
    return render_template('settings.html', user_name=get_display_name(), role=session['role'], valid_dates=current_dates)

@app.route('/shifts')
def shifts_list():
    if 'user_name' not in session or session.get('role') not in ['owner', 'admin']:
        return redirect(url_for('index'))
        
    # 🌟 DBから全シフトを取得
    res = requests.get(f"{SUPABASE_URL}/rest/v1/shifts?select=*,users(last_name)", headers=get_headers())
    shifts = res.json() if res.status_code == 200 else []
    return render_template('shifts.html', user_name=get_display_name(), role=session['role'], shifts=shifts)

# 🌟 追加：自分の未確定シフトを削除する機能
@app.route('/delete_shift', methods=['POST'])
def delete_shift():
    if 'user_name' not in session: return jsonify({"status": "error"}), 401
    
    shift_id = request.json.get('shift_id')
    username = session['user_name'] # 現在ログインしている人
    
    # 🌟 安全装置：対象ID ＋ 本人のもの ＋ 「未確定」であること を条件に削除！
    requests.delete(f"{SUPABASE_URL}/rest/v1/shifts?id=eq.{shift_id}&username=eq.{username}&status=eq.未確定", headers=get_headers())
    return jsonify({"status": "success"})

def open_browser():
    webbrowser.open_new("http://127.0.0.1:5000")

# 🌟 ひろ自作の「権限変更機能」をSupabaseに繋ぐ専用API
@app.route('/admin/update_role', methods=['POST'])
def update_role():
    # オーナー以外が直接アクセスしてきたら弾く
    if 'user_name' not in session or session.get('role') != 'owner':
        return jsonify({"status": "error"}), 403
        
    data = request.json
    target_username = data.get('username')
    new_role = data.get('role')
    
    if target_username and new_role:
        # Supabaseのデータを書き換え
        requests.patch(f"{SUPABASE_URL}/rest/v1/users?username=eq.{target_username}", headers=get_headers(), json={'role': new_role})
        return jsonify({"status": "success"})
        
    return jsonify({"status": "error"}), 400

# 🌟 追加：ユーザーID（ログインID）を変更する機能（オーナー専用）
@app.route('/admin/change_userid', methods=['POST'])
def change_userid():
    if session.get('role') != 'owner':
        return jsonify({"status": "error", "message": "権限がありません"}), 403
        
    old_username = request.json.get('old_username')
    new_username = request.json.get('new_username')

    # 1. 新しいIDが、すでに他の人に使われていないかチェック！
    check_res = requests.get(f"{SUPABASE_URL}/rest/v1/users?username=eq.{new_username}", headers=get_headers())
    if check_res.status_code == 200 and check_res.json():
        return jsonify({"status": "error", "message": "そのIDはすでに使われています！別のIDにしてください。"}), 400

    # 2. SupabaseのIDを新しいものに書き換える（PATCH）
    res = requests.patch(f"{SUPABASE_URL}/rest/v1/users?username=eq.{old_username}", headers=get_headers(), json={'username': new_username})
    
    if res.status_code in [200, 204]:
        return jsonify({"status": "success"})
    else:
        print("❌ Supabaseエラー:", res.text) 
        return jsonify({"status": "error", "message": "変更に失敗しました。（シフトが紐づいている可能性があります）"}), 500

# 🌟 登録済みユーザーを削除する機能（オーナー専用）
@app.route('/admin/delete_user', methods=['POST'])
def delete_user():
    if session.get('role') != 'owner':
        return jsonify({"status": "error", "message": "権限がありません"}), 403
        
    target_username = request.json.get('username')
    
    if target_username == session.get('user_name'):
        return jsonify({"status": "error", "message": "自分自身は削除できません！"}), 400

    # 🌟 修正1：ユーザー本体を消す前に、その人が提出した「シフト」を道連れにして全て削除する！
    requests.delete(f"{SUPABASE_URL}/rest/v1/shifts?username=eq.{target_username}", headers=get_headers())

    # 🌟 修正2：シフトが綺麗になった後で、ユーザー本体を削除する！
    res = requests.delete(f"{SUPABASE_URL}/rest/v1/users?username=eq.{target_username}", headers=get_headers())
    
    if res.status_code in [200, 204]: 
        return jsonify({"status": "success"})
    else:
        # 🌟 修正3：もしまた失敗した時のために、ターミナルにSupabaseからのエラー詳細を表示させる
        print("❌ Supabaseエラー:", res.text) 
        return jsonify({"status": "error", "message": "削除に失敗しました。"}), 500

if __name__ == '__main__':
    if not os.environ.get('VERCEL'):
        Timer(1, open_browser).start()
        app.run(debug=True, use_reloader=False)