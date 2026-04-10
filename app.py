import csv
import os
from datetime import datetime
from flask import Flask, render_template, request, session, redirect, url_for, jsonify
import webbrowser
from threading import Timer

app = Flask(__name__)
app.secret_key = "super_secret_key_hiro"

USERS = {
    "hiro": {"pass": "1234", "role": "admin"},
    "miku": {"pass": "5678", "role": "user"}
}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username in USERS and USERS[username]["pass"] == password:
            session['user_name'] = username
            session['role'] = USERS[username]["role"]
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="IDかパスワードが違います")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_name', None)
    session.pop('role', None)
    return redirect(url_for('login'))

@app.route('/')
def index():
    if 'user_name' not in session:
        return redirect(url_for('login'))
    return render_template('index.html', user_name=session['user_name'], role=session['role'])

# --- 📋 シフト一覧画面 ---
@app.route('/shifts')
def view_shifts():
    if 'user_name' not in session:
        return redirect(url_for('login'))
    
    file_name = 'shift_data.csv'
    shifts = []
    
    if os.path.exists(file_name):
        with open(file_name, mode='r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for row in reader:
                shifts.append(row)
    if shifts:
        shifts.sort(key=lambda x: (x[2], x[3]))
                
    return render_template('shifts.html', shifts=shifts, user_name=session['user_name'], role=session['role'])

# --- 🌟 新機能：シフトを「確定」する処理 ---
@app.route('/approve', methods=['POST'])
def approve():
    # 管理者以外は弾く
    if session.get('role') != 'admin':
        return redirect(url_for('view_shifts'))
        
    row_index = int(request.form.get('row_index')) # 何行目のボタンが押されたかを受け取る
    file_name = 'shift_data.csv'
    
    # 1. 一度すべてのデータを読み込む
    rows = []
    with open(file_name, mode='r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        rows = list(reader)
        
    # 2. 該当する行のステータス（5番目の要素）を「確定」に書き換える
    if 0 <= row_index < len(rows):
        rows[row_index][5] = '✅ 確定'
        
    # 3. CSVファイルを上書き保存する
    with open(file_name, mode='w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header) # 見出しを戻す
        writer.writerows(rows)  # 書き換えたデータを全部戻す
        
    return redirect(request.referrer or url_for('view_shifts')) # 元いた画面に戻る！

# --- 📤 提出処理 ---
@app.route('/submit', methods=['POST'])
def submit():
    if 'user_name' not in session:
        return redirect(url_for('login'))

    user_name = session['user_name']
    date = request.form.get('date')
    time_slots = request.form.getlist('time_slot')
    memo = request.form.get('memo')
    
    if not time_slots:
        return render_template('index.html', message='時間帯を１つ以上選択してください。', msg_type='error', user_name=user_name, role=session.get('role'))
    
    file_name = 'shift_data.csv'
    file_exists = os.path.isfile(file_name)
    
    with open(file_name, mode='a', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['送信日時', 'ユーザー名', 'シフト希望日', '希望時間帯', '補足メモ', '状態'])
        
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 🌟 変更ここから：選ばれた時間帯のリストを1つずつ取り出して、別々の行として保存する！
        for slot in time_slots:
            writer.writerow([now, user_name, date, slot, memo, '未確定'])
        # 🌟 変更ここまで

    # メッセージ用にカンマ区切りの文字列も作っておく（画面に表示する用）
    shift_str = ', '.join(time_slots)
    success_msg = f"{date} のシフト（{shift_str}）を受け付けました！"
    
    return render_template('index.html', message=success_msg, msg_type='success', user_name=user_name, role=session.get('role'))

@app.route('/submit_bulk', methods=['POST'])
def submit_bulk():
    if 'user_name' not in session:
        return jsonify({"status": "error"}), 401

    data = request.json
    all_shifts = data.get('shifts') # { "日付": ["時間帯", "時間帯"], ... }
    memo = data.get('memo')
    user_name = session['user_name']
    
    file_name = 'shift_data.csv'
    file_exists = os.path.isfile(file_name)
    
    with open(file_name, mode='a', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(['送信日時', 'ユーザー名', 'シフト希望日', '希望時間帯', '補足メモ', '状態'])
        
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        for date, slots in all_shifts.items():
            for slot in slots:
                # 1つずつCSVの行として書き込む
                writer.writerow([now, user_name, date, slot, memo, '未確定'])
                
    return jsonify({"status": "success"})


# ==========================================
# 📅 カレンダー画面の表示
# ==========================================
@app.route('/calendar')
def show_calendar():
    if 'user_name' not in session:
        return redirect(url_for('login'))
    return render_template('calendar.html', user_name=session['user_name'], role=session['role'])

# ==========================================
# 📅 カレンダーにデータを渡すAPI（進化版！）
# ==========================================
@app.route('/api/shifts')
def get_confirmed_shifts():
    file_name = 'shift_data.csv'
    events = []
    user_name = session.get('user_name') # ログイン中のユーザー名
    role = session.get('role')
    
    if os.path.exists(file_name):
        with open(file_name, mode='r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            next(reader, None)
            for index, row in enumerate(reader):
                if len(row) >= 6:
                    status = row[5]
                    submitter = row[1] # 提出者名
                    time_range = row[3]
                    
                    # 時間帯の数字を削る
                    display_time = time_range.split('. ')[1] if '. ' in time_range else time_range
                    event_title = f"{submitter} ({display_time})"
                    
                    # 1. すでに確定しているシフト（全員分表示）
                    if '✅ 確定' in status:
                        events.append({
                            "title": event_title,
                            "start": row[2],
                            "backgroundColor": "#28a745",
                            "borderColor": "#28a745",
                            "extendedProps": {"status": "confirmed", "index": index}
                        })
                    
                    # 2. 管理者の場合：すべての未確定シフトを表示（黄色）
                    elif role == 'admin' and '未確定' in status:
                        events.append({
                            "title": "【未】" + event_title,
                            "start": row[2],
                            "backgroundColor": "#ffc107",
                            "borderColor": "#ffc107",
                            "textColor": "#212529",
                            "extendedProps": {"status": "pending", "index": index}
                        })
                    
                    # 3. 一般ユーザーの場合：自分の未確定シフトだけを表示（薄い青など）
                    elif role != 'admin' and submitter == user_name and '未確定' in status:
                        events.append({
                            "title": "【提出中】" + display_time, # 自分のは名前不要なので時間だけ
                            "start": row[2],
                            "backgroundColor": "#e7f1ff", # 目立ちすぎない薄い青
                            "borderColor": "#007bff",
                            "textColor": "#007bff",
                            "extendedProps": {"status": "my_pending", "index": index}
                        })
                        
    return jsonify(events)

def open_browser():
    webbrowser.open_new('http://127.0.0.1:5000/')

if __name__ == '__main__':
    Timer(1, open_browser).start()
    app.run(debug=True, use_reloader=False)