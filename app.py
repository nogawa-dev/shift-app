import os
import json
import jpholiday
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from threading import Timer
import webbrowser
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_key_hiro')

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

SESSION_TIMEOUT = 30 * 60  # 30分（秒単位）

@app.before_request
def check_session_timeout():
    # ログイン不要なページはスキップ
    if request.endpoint in ('login', 'forgot_password', 'static'):
        return
    if 'user_name' not in session:
        return
    last_activity = session.get('last_activity')
    now = datetime.now().timestamp()
    if last_activity and now - last_activity > SESSION_TIMEOUT:
        session.clear()
        return redirect(url_for('login'))
    session['last_activity'] = now

def get_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

def get_display_name():
    return session.get('last_name', 'ゲスト')

def load_valid_dates():
    try:
        res = requests.get(f"{SUPABASE_URL}/rest/v1/settings?id=eq.1&select=valid_dates", headers=get_headers())
        if res.status_code == 200 and res.json():
            return json.loads(res.json()[0]['valid_dates'])
    except Exception as e:
        print(e)
    return []

def verify_password(stored, provided):
    # ハッシュ済みならcheck_password_hash、平文（移行前）ならそのまま比較
    if stored.startswith('pbkdf2:') or stored.startswith('scrypt:'):
        return check_password_hash(stored, provided)
    return stored == provided

def get_all_users():
    res = requests.get(f"{SUPABASE_URL}/rest/v1/users?select=*", headers=get_headers())
    users_data = res.json() if res.status_code == 200 else []
    return {u['username']: {"pass": u['password'], "role": u['role'], "last_name": u.get('last_name', '')} for u in users_data}


@app.route('/change_password', methods=['POST'])
def change_password():
    if 'user_name' not in session:
        return jsonify({"status": "error"}), 401
    new_password = request.json.get('new_password')
    if not new_password:
        return jsonify({"status": "error"}), 400
    hashed = generate_password_hash(new_password)
    requests.patch(f"{SUPABASE_URL}/rest/v1/users?username=eq.{session['user_name']}", headers=get_headers(), json={'password': hashed})
    return jsonify({"status": "success"})


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        res = requests.get(f"{SUPABASE_URL}/rest/v1/users?username=eq.{username}&select=*", headers=get_headers())
        if res.status_code == 200 and res.json():
            user = res.json()[0]
            if verify_password(user['password'], password):
                session['user_name'] = username
                session['role'] = user['role']
                session['last_name'] = user.get('last_name', '')
                return redirect(url_for('setup') if not session['last_name'] else url_for('index'))
        return render_template('login.html', error="IDかパスワードが違います")
    return render_template('login.html')


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if 'user_name' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        last_name = request.form.get('last_name')
        new_password = request.form.get('password')
        update_data = {'last_name': last_name}
        if new_password:
            update_data['password'] = generate_password_hash(new_password)
        requests.patch(f"{SUPABASE_URL}/rest/v1/users?username=eq.{session['user_name']}", headers=get_headers(), json=update_data)
        session['last_name'] = last_name
        return redirect(url_for('index'))
    return render_template('setup.html')


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username')
        last_name = request.form.get('last_name')
        new_password = request.form.get('new_password')
        res = requests.get(f"{SUPABASE_URL}/rest/v1/users?username=eq.{username}&last_name=eq.{last_name}&select=*", headers=get_headers())
        if res.status_code == 200 and res.json():
            hashed = generate_password_hash(new_password)
            requests.patch(f"{SUPABASE_URL}/rest/v1/users?username=eq.{username}", headers=get_headers(), json={'password': hashed})
            return render_template('forgot.html', success="パスワードをリセットしました！新しいパスワードでログインしてください。")
        return render_template('forgot.html', error="IDかカレンダー表示名が間違っています。")
    return render_template('forgot.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
def index():
    if 'user_name' not in session:
        return redirect(url_for('login'))
    if not session.get('last_name'):
        return redirect(url_for('setup'))
    return render_template('index.html', user_name=get_display_name(), role=session['role'], valid_dates=load_valid_dates())


@app.route('/calendar')
def calendar():
    if 'user_name' not in session:
        return redirect(url_for('login'))
    if not session.get('last_name'):
        return redirect(url_for('setup'))
    return render_template('calendar.html', user_name=get_display_name(), role=session['role'])


@app.route('/api/shifts')
def api_shifts():
    if 'user_name' not in session:
        return jsonify([])
    res = requests.get(f"{SUPABASE_URL}/rest/v1/shifts?select=*,users(last_name)", headers=get_headers())
    shifts = res.json() if res.status_code == 200 else []
    role = session.get('role')
    current_user = session.get('user_name')
    events = []
    seen_shift_ids = set()


    for shift in shifts:
        status = shift.get('status', '未確定')
        shift_id = shift.get('id')
        if shift_id in seen_shift_ids:
            continue
        seen_shift_ids.add(shift_id)
        display_name = shift['users']['last_name']
        time_slot = shift['time_slot']
        display_time = time_slot.split('. ')[1] if '. ' in time_slot else time_slot
        event_title = f"{display_name} ({display_time})"
        shift_date = shift['shift_date']
        order_key = time_slot.split('.')[0] if '.' in time_slot else '99'

        if status == '確定':
            events.append({"title": event_title, "start": shift_date, "backgroundColor": "#28a745", "borderColor": "#28a745", "extendedProps": {"status": "confirmed", "id": shift_id, "orderId": order_key}})
        elif role in ['owner', 'admin'] and status == '未確定':
            events.append({"title": "【未】" + event_title, "start": shift_date, "backgroundColor": "#ffc107", "borderColor": "#ffc107", "textColor": "#212529", "extendedProps": {"status": "pending", "id": shift_id, "orderId": order_key}})
        elif role == 'user' and shift['username'] == current_user and status == '未確定':
            events.append({"title": "【提出中】" + display_time, "start": shift_date, "backgroundColor": "#e7f1ff", "borderColor": "#007bff", "textColor": "#007bff", "extendedProps": {"status": "my_pending", "id": shift_id, "orderId": order_key}})

    return jsonify(events)


@app.route('/approve', methods=['POST'])
def approve_shift():
    if 'user_name' not in session or session.get('role') not in ['owner', 'admin']:
        return redirect(url_for('calendar'))
    shift_id = request.form.get('shift_id')
    if shift_id:
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
    payload = [
        {'username': username, 'shift_date': date, 'time_slot': slot, 'memo': memo, 'status': '未確定'}
        for date, slots in shifts_data.items()
        for slot in slots
    ]
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
        
        # --- 追加：既存ユーザーのチェック ---
        existing_users = get_all_users()
        if new_username in existing_users:
            return render_template('register.html', 
                                 error=f"ID「{new_username}」は既に登録されています。", 
                                 user_name=get_display_name(), 
                                 role=session['role'], 
                                 users=existing_users)
        # -------------------------------

        res = requests.post(f"{SUPABASE_URL}/rest/v1/users", headers=get_headers(), json={
            'username': new_username, 'password': generate_password_hash(new_password), 'role': new_role, 'last_name': ''
        })
        users_dict = get_all_users()
        if res.status_code in [200, 201]:
            return render_template('register.html', success=f"ユーザー「{new_username}」を登録しました！", user_name=get_display_name(), role=session['role'], users=users_dict)
        return render_template('register.html', error="登録に失敗しました（詳細はターミナルを確認）", user_name=get_display_name(), role=session['role'], users=users_dict)
    return render_template('register.html', user_name=get_display_name(), role=session['role'], users=get_all_users())


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
            requests.patch(f"{SUPABASE_URL}/rest/v1/settings?id=eq.1", headers=get_headers(), json={'valid_dates': json.dumps(valid_dates)})
            return render_template('settings.html', success="募集期間を更新しました！", user_name=get_display_name(), role=session['role'], valid_dates=valid_dates)
    return render_template('settings.html', user_name=get_display_name(), role=session['role'], valid_dates=load_valid_dates())


@app.route('/shifts')
def shifts_list():
    if 'user_name' not in session or session.get('role') not in ['owner', 'admin']:
        return redirect(url_for('index'))
    res = requests.get(f"{SUPABASE_URL}/rest/v1/shifts?select=*,users(last_name)", headers=get_headers())
    shifts = res.json() if res.status_code == 200 else []
    return render_template('shifts.html', user_name=get_display_name(), role=session['role'], shifts=shifts)


@app.route('/delete_shift', methods=['POST'])
def delete_shift():
    if 'user_name' not in session:
        return jsonify({"status": "error"}), 401
    shift_id = request.json.get('shift_id')
    username = session['user_name']
    requests.delete(f"{SUPABASE_URL}/rest/v1/shifts?id=eq.{shift_id}&username=eq.{username}&status=eq.未確定", headers=get_headers())
    return jsonify({"status": "success"})


@app.route('/admin/update_role', methods=['POST'])
def update_role():
    if 'user_name' not in session or session.get('role') != 'owner':
        return jsonify({"status": "error"}), 403
    data = request.json
    target_username = data.get('username')
    new_role = data.get('role')
    if target_username and new_role:
        requests.patch(f"{SUPABASE_URL}/rest/v1/users?username=eq.{target_username}", headers=get_headers(), json={'role': new_role})
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 400


@app.route('/admin/change_userid', methods=['POST'])
def change_userid():
    if session.get('role') != 'owner':
        return jsonify({"status": "error", "message": "権限がありません"}), 403
    old_username = request.json.get('old_username')
    new_username = request.json.get('new_username')
    check_res = requests.get(f"{SUPABASE_URL}/rest/v1/users?username=eq.{new_username}", headers=get_headers())
    if check_res.status_code == 200 and check_res.json():
        return jsonify({"status": "error", "message": "そのIDはすでに使われています！別のIDにしてください。"}), 400
    res = requests.patch(f"{SUPABASE_URL}/rest/v1/users?username=eq.{old_username}", headers=get_headers(), json={'username': new_username})
    if res.status_code in [200, 204]:
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "変更に失敗しました。（シフトが紐づいている可能性があります）"}), 500


@app.route('/admin/delete_user', methods=['POST'])
def delete_user():
    if session.get('role') != 'owner':
        return jsonify({"status": "error", "message": "権限がありません"}), 403
    target_username = request.json.get('username')
    if target_username == session.get('user_name'):
        return jsonify({"status": "error", "message": "自分自身は削除できません！"}), 400
    requests.delete(f"{SUPABASE_URL}/rest/v1/shifts?username=eq.{target_username}", headers=get_headers())
    res = requests.delete(f"{SUPABASE_URL}/rest/v1/users?username=eq.{target_username}", headers=get_headers())
    if res.status_code in [200, 204]:
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "削除に失敗しました。"}), 500


def open_browser():
    webbrowser.open_new("http://127.0.0.1:5000")

if __name__ == '__main__':
    if not os.environ.get('VERCEL'):
        Timer(1, open_browser).start()
        app.run(debug=True, use_reloader=False)
