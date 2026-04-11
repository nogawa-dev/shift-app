import json
import jpholiday
import csv
import os
from datetime import datetime
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
import webbrowser
from threading import Timer

app = Flask(__name__)
app.secret_key = "super_secret_key_hiro"

# --- 👤 ユーザー管理機能 ---
USER_FILE = 'users.csv'

def load_users():
    users = {}
    if not os.path.exists(USER_FILE):
        with open(USER_FILE, mode='w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['username', 'password', 'role', 'last_name'])
            # 🌟 ひろの初期権限を 'admin' から 'owner' に昇格！
            writer.writerow(['hiro', '1234', 'owner', '野川'])
        return {"hiro": {"pass": "1234", "role": "owner", "last_name": "野川"}}
    
    with open(USER_FILE, mode='r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 4:
                users[row[0]] = {"pass": row[1], "role": row[2], "last_name": row[3]}
    return users

@app.route('/login', methods=['GET', 'POST'])
def login():
    users = load_users()
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username in users and users[username]["pass"] == password:
            session['user_name'] = username
            session['role'] = users[username]["role"]
            session['last_name'] = users[username]["last_name"]
            
            if not session['last_name']: return redirect(url_for('setup'))
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="IDかパスワードが違います")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    if 'user_name' not in session: return redirect(url_for('login'))
    if session.get('last_name'): return redirect(url_for('index'))

    if request.method == 'POST':
        new_name = request.form.get('last_name')
        new_pass = request.form.get('password')
        user_id = session['user_name']

        if new_name and new_pass:
            users_data = []
            with open(USER_FILE, mode='r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                header = next(reader)
                for row in reader:
                    while len(row) < 4: row.append("")
                    if row[0] == user_id:
                        row[1] = new_pass
                        row[3] = new_name
                    users_data.append(row)

            with open(USER_FILE, mode='w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer.writerows(users_data)

            session['last_name'] = new_name
            return redirect(url_for('index'))
    return render_template('setup.html')

# --- 🆕 誰でも使える：パスワードリセット機能 ---
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        user_id = request.form.get('username')
        last_name = request.form.get('last_name')
        new_password = request.form.get('new_password')
        
        users_data = []
        match_success = False
        
        with open(USER_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            header = next(reader)
            for row in reader:
                while len(row) < 4: row.append("")
                # IDと名字（カレンダー表示名）が両方一致するかチェック！
                if row[0] == user_id and row[3] == last_name:
                    match_success = True
                    row[1] = new_password # パスワードを上書き
                users_data.append(row)
                
        if not match_success:
            return render_template('forgot.html', error="IDかカレンダー表示名が間違っています。")
            
        # CSVを上書き保存
        with open(USER_FILE, mode='w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(users_data)
            
        return render_template('forgot.html', success="パスワードをリセットしました！新しいパスワードでログインしてください。")
        
    return render_template('forgot.html')

# --- 🆕 オーナー専用：ユーザー追加API ---
@app.route('/admin/add_user', methods=['POST'])
def add_user():
    # 🌟 変更：オーナーしか追加できないようにする
    if session.get('role') != 'owner':
        return jsonify({"status": "error", "message": "権限がありません"}), 403
    
    data = request.json
    new_user = data.get('username')
    new_pass = data.get('password')
    new_role = data.get('role', 'user')
    
    if not new_user or not new_pass: return jsonify({"status": "error", "message": "入力が足りません"}), 400

    with open(USER_FILE, mode='a', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([new_user, new_pass, new_role, ""])
    return jsonify({"status": "success"})

# --- 📅 募集期間の設定管理 ---
SETTINGS_FILE = 'settings.json'

def load_valid_dates():
    """現在募集中の日付リストを読み込む"""
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f).get("valid_dates", [])
    return []

# --- 🆕 管理者・オーナー専用：募集設定画面 ---
@app.route('/settings', methods=['GET', 'POST'])
def shift_settings():
    if 'user_name' not in session: return redirect(url_for('login'))
    if not session.get('last_name'): return redirect(url_for('setup'))
    
    # 🌟 オーナーか管理者しかアクセスできない
    if session.get('role') not in ['owner', 'admin']: 
        return redirect(url_for('index'))

    if request.method == 'POST':
        start_str = request.form.get('start_date')
        end_str = request.form.get('end_date')

        if start_str and end_str:
            from datetime import timedelta # 上でimportし忘れた時用
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d')
            valid_dates = []

            current = start_date
            while current <= end_date:
                # 🌟 weekday() は 0:月 ~ 4:金, 5:土, 6:日
                # 平日(5未満) かつ 祝日ではない日だけを追加！
                if current.weekday() < 5 and not jpholiday.is_holiday(current.date()):
                    valid_dates.append(current.strftime('%Y-%m-%d'))
                current += timedelta(days=1)

            # JSONファイルとして保存
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump({"valid_dates": valid_dates}, f)

            return render_template('settings.html', success="募集期間を更新しました！", user_name=get_display_name(), role=session['role'], valid_dates=valid_dates)

    # 現在の設定を読み込んで表示
    current_dates = load_valid_dates()
    return render_template('settings.html', user_name=get_display_name(), role=session['role'], valid_dates=current_dates)

# --- 🌟 index関数の書き換え（募集中の日だけを表示するように） ---
@app.route('/')
def index():
    if 'user_name' not in session: return redirect(url_for('login'))
    if not session.get('last_name'): return redirect(url_for('setup'))
    
    # 設定された募集日だけを入力画面に渡す！
    valid_dates = load_valid_dates()
    return render_template('index.html', user_name=get_display_name(), role=session['role'], valid_dates=valid_dates)

# ==========================================
# 画面表示系
# ==========================================
def get_display_name():
    last_name = session.get('last_name')
    return last_name if last_name else session.get('user_name')

@app.route('/shifts')
def view_shifts():
    if 'user_name' not in session: return redirect(url_for('login'))
    if not session.get('last_name'): return redirect(url_for('setup'))
    
    # 🌟 変更：オーナーと管理者は見れる
    if session.get('role') not in ['owner', 'admin']: 
        return redirect(url_for('index'))
    
    file_name = 'shift_data.csv'
    shifts = []
    if os.path.exists(file_name):
        with open(file_name, mode='r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for row in reader: shifts.append(row)
    if shifts: shifts.sort(key=lambda x: (x[2], x[3]))
    return render_template('shifts.html', shifts=shifts, user_name=get_display_name(), role=session['role'])

@app.route('/calendar')
def show_calendar():
    if 'user_name' not in session: return redirect(url_for('login'))
    if not session.get('last_name'): return redirect(url_for('setup'))
    return render_template('calendar.html', user_name=get_display_name(), role=session['role'])

# --- 🆕 オーナー専用：ユーザー登録画面タブ ---
@app.route('/register_users')
def register_users():
    if 'user_name' not in session: return redirect(url_for('login'))
    if not session.get('last_name'): return redirect(url_for('setup'))
    if session.get('role') != 'owner': return redirect(url_for('index'))
    
    # 🌟 変更：画面に一覧を出すために、全ユーザーのデータを読み込んで渡す
    users = load_users()
    return render_template('register.html', user_name=get_display_name(), role=session['role'], users=users)

# --- 🆕 オーナー専用：既存ユーザーの権限変更API ---
@app.route('/admin/update_role', methods=['POST'])
def update_role():
    if session.get('role') != 'owner':
        return jsonify({"status": "error", "message": "権限がありません"}), 403

    data = request.json
    target_user = data.get('username')
    new_role = data.get('role')

    if not target_user or not new_role:
        return jsonify({"status": "error", "message": "データが不足しています"}), 400

    # CSVを読み込んで、指定されたユーザーの権限だけ書き換える
    users_data = []
    with open(USER_FILE, mode='r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            if row[0] == target_user:
                row[2] = new_role # 🌟 権限（3番目の要素）を上書き
            users_data.append(row)

    # 上書き保存
    with open(USER_FILE, mode='w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(users_data)

    return jsonify({"status": "success"})


# ==========================================
# シフトデータ処理系
# ==========================================
@app.route('/approve', methods=['POST'])
def approve():
    # 🌟 変更：オーナーと管理者は確定できる
    if session.get('role') not in ['owner', 'admin']: return redirect(url_for('view_shifts'))
    row_index = int(request.form.get('row_index'))
    file_name = 'shift_data.csv'
    rows = []
    with open(file_name, mode='r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        rows = list(reader)
    if 0 <= row_index < len(rows): rows[row_index][5] = '✅ 確定'
    with open(file_name, mode='w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    return redirect(request.referrer or url_for('view_shifts'))

@app.route('/submit', methods=['POST'])
def submit():
    if 'user_name' not in session: return redirect(url_for('login'))
    user_id = session['user_name']
    date = request.form.get('date')
    time_slots = request.form.getlist('time_slot')
    memo = request.form.get('memo')
    if not time_slots: return render_template('index.html', message='時間帯を選択してください。', msg_type='error', user_name=get_display_name(), role=session.get('role'))
    file_name = 'shift_data.csv'
    file_exists = os.path.isfile(file_name)
    with open(file_name, mode='a', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        if not file_exists: writer.writerow(['送信日時', 'ユーザー名', 'シフト希望日', '希望時間帯', '補足メモ', '状態'])
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for slot in time_slots: writer.writerow([now, user_id, date, slot, memo, '未確定'])
    return render_template('index.html', message="シフトを受け付けました！", msg_type='success', user_name=get_display_name(), role=session.get('role'))

@app.route('/submit_bulk', methods=['POST'])
def submit_bulk():
    if 'user_name' not in session: return jsonify({"status": "error"}), 401
    data = request.json
    all_shifts = data.get('shifts')
    memo = data.get('memo')
    user_id = session['user_name']
    file_name = 'shift_data.csv'
    file_exists = os.path.isfile(file_name)
    with open(file_name, mode='a', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        if not file_exists: writer.writerow(['送信日時', 'ユーザー名', 'シフト希望日', '希望時間帯', '補足メモ', '状態'])
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for date, slots in all_shifts.items():
            for slot in slots: writer.writerow([now, user_id, date, slot, memo, '未確定'])
    return jsonify({"status": "success"})

@app.route('/api/shifts')
def get_confirmed_shifts():
    file_name = 'shift_data.csv'
    events = []
    user_id = session.get('user_name')
    role = session.get('role')
    users = load_users()
    if os.path.exists(file_name):
        with open(file_name, mode='r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            next(reader, None)
            for index, row in enumerate(reader):
                if len(row) >= 6:
                    status = row[5]
                    submitter_id = row[1]
                    time_range = row[3]
                    display_name = users.get(submitter_id, {}).get("last_name") or submitter_id
                    display_time = time_range.split('. ')[1] if '. ' in time_range else time_range
                    event_title = f"{display_name} ({display_time})"
                    
                    if '✅ 確定' in status:
                        events.append({"title": event_title, "start": row[2], "backgroundColor": "#28a745", "borderColor": "#28a745", "extendedProps": {"status": "confirmed", "index": index}})
                    
                    # 🌟 変更：オーナーと管理者は全ての未確定を見れる
                    elif role in ['owner', 'admin'] and '未確定' in status:
                        events.append({"title": "【未】" + event_title, "start": row[2], "backgroundColor": "#ffc107", "borderColor": "#ffc107", "textColor": "#212529", "extendedProps": {"status": "pending", "index": index}})
                    
                    elif role == 'user' and submitter_id == user_id and '未確定' in status:
                        events.append({"title": "【提出中】" + display_time, "start": row[2], "backgroundColor": "#e7f1ff", "borderColor": "#007bff", "textColor": "#007bff", "extendedProps": {"status": "my_pending", "index": index}})
    return jsonify(events)

def open_browser(): webbrowser.open_new('http://127.0.0.1:5000/')

if __name__ == '__main__':
    Timer(1, open_browser).start()
    app.run(debug=True, use_reloader=False)