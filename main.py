from flask import Flask, render_template, request, jsonify, session, send_file, Response, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import os
from groq import Groq
import sqlite3
from datetime import datetime
import json
import io

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

client = Groq(api_key=os.getenv('GROQ_API_KEY'))

# Database setup
def init_db():
    conn = sqlite3.connect('interviews.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL,
                  created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS interviews
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT,
                  user_id INTEGER,
                  interview_type TEXT,
                  difficulty TEXT,
                  timestamp TEXT,
                  messages TEXT,
                  rating INTEGER,
                  duration INTEGER,
                  message_count INTEGER,
                  title TEXT)''')
    
    # Safe migrations — add columns if they don't exist yet
    existing_columns = [row[1] for row in c.execute('PRAGMA table_info(interviews)').fetchall()]
    if 'user_id' not in existing_columns:
        c.execute('ALTER TABLE interviews ADD COLUMN user_id INTEGER')
    if 'title' not in existing_columns:
        c.execute('ALTER TABLE interviews ADD COLUMN title TEXT')
    
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def home():
    if 'session_id' not in session:
        session['session_id'] = os.urandom(16).hex()
    session['start_time'] = datetime.now().isoformat()
    return render_template('index.html')

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'success': False, 'error': 'Username and password are required'}), 400
    if len(username) < 3:
        return jsonify({'success': False, 'error': 'Username must be at least 3 characters'}), 400
    if len(password) < 6:
        return jsonify({'success': False, 'error': 'Password must be at least 6 characters'}), 400

    try:
        conn = sqlite3.connect('interviews.db')
        c = conn.cursor()
        c.execute('INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)',
                  (username, generate_password_hash(password), datetime.now().isoformat()))
        conn.commit()
        user_id = c.lastrowid
        conn.close()

        session['user_id'] = user_id
        session['username'] = username
        return jsonify({'success': True, 'username': username})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'error': 'Username already taken'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')

    try:
        conn = sqlite3.connect('interviews.db')
        c = conn.cursor()
        c.execute('SELECT id, password_hash FROM users WHERE username = ?', (username,))
        row = c.fetchone()
        conn.close()

        if not row or not check_password_hash(row[1], password):
            return jsonify({'success': False, 'error': 'Invalid username or password'}), 401

        session['user_id'] = row[0]
        session['username'] = username
        return jsonify({'success': True, 'username': username})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    return jsonify({'success': True})

@app.route('/auth_status', methods=['GET'])
def auth_status():
    return jsonify({
        'logged_in': 'user_id' in session,
        'username': session.get('username', None)
    })

def generate_interview_title(conversation, interview_type):
    try:
        if not conversation or len(conversation) < 2:
            return f"{interview_type.title()} Interview"
        
        # Take first 3 exchanges max to generate title
        sample = conversation[:6]
        sample_text = ' '.join([m['content'][:200] for m in sample])
        
        title_response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "Generate a short, specific 4-7 word title for this interview session. Just the title, nothing else. No quotes."},
                {"role": "user", "content": f"Interview type: {interview_type}\nConversation sample: {sample_text}"}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.5,
            max_tokens=20
        )
        title = title_response.choices[0].message.content.strip()
        return title[:60]  # cap at 60 chars
    except:
        return f"{interview_type.title()} Interview"

# System prompts for different interview types and difficulties
def get_system_prompts():
    return {
        'coding': {
            'easy': """You are an expert technical interviewer at a top tech company.

Ask EASY coding questions suitable for junior developers and new graduates.
Examples: Two Sum, Reverse String, Valid Palindrome, FizzBuzz

After each answer:
- Explain time/space complexity
- Suggest optimizations
- Be very encouraging
- Ask follow-up questions

Use markdown with code blocks. Keep explanations clear and simple.""",
            
            'medium': """You are an expert technical interviewer at a top tech company.

Ask MEDIUM difficulty coding questions (LeetCode Medium level).
Focus on: arrays, hashmaps, trees, graphs, BFS, DFS, dynamic programming basics.

After each answer:
- Analyze time/space complexity
- Discuss edge cases
- Suggest optimizations
- Ask about alternative approaches

Use markdown with code blocks.""",
            
            'hard': """You are an expert technical interviewer at FAANG companies.

Ask HARD coding questions (LeetCode Hard level).
Advanced algorithms: DP, graphs, trees, optimization.

After each answer:
- Deep dive into complexity analysis
- Discuss all edge cases
- Compare multiple solutions
- Ask about scalability

Be rigorous but fair. Use markdown with code blocks."""
        },
        
        'behavioral': {
            'easy': """You are a friendly HR interviewer for entry-level positions.

Ask basic behavioral questions using STAR method:
- Tell me about yourself
- Why this company?
- Describe a team project

Be warm and encouraging. Help them structure answers.""",
            
            'medium': """You are an experienced HR interviewer for mid-level positions.

Ask deeper behavioral questions:
- Describe a conflict with a coworker
- Tell me about a failed project
- Leadership experience

Probe for specifics. Ask follow-ups like "What was the outcome?"
Look for self-awareness and growth mindset.""",
            
            'hard': """You are a senior executive interviewer for leadership roles.

Ask challenging behavioral questions:
- Biggest professional failure and learnings
- How you influenced organizational change
- Making unpopular decisions
- Handling ambiguity

Expect detailed, reflective answers. Probe deeply. Assess strategic thinking."""
        },
        
        'system design': {
            'easy': """You are a system design interviewer for junior positions.

Ask simple system design questions:
- Design a URL shortener
- Design a basic chat app
- Design a parking lot system

Guide them through: requirements, high-level design, database schema, APIs.
Be patient and helpful.""",
            
            'medium': """You are a system design interviewer for mid-level engineers.

Ask moderate system design questions:
- Design Instagram
- Design Twitter feed
- Design Netflix

Discuss: scalability, database choices, APIs, microservices, trade-offs.
Ask about specific numbers (DAU, QPS, storage).""",
            
            'hard': """You are a system design interviewer for senior engineers.

Ask complex system design questions:
- Design Google Search
- Design distributed cache
- Design payment system

Expect deep discussion of: distributed systems, CAP theorem, partitioning, 
replication, fault tolerance, monitoring, cost optimization.

Challenge design choices. Discuss failure scenarios."""
        },
        
        'general': {
            'easy': """You are a friendly AI interviewer. Be conversational and supportive.""",
            'medium': """You are an AI interviewer. Be helpful but thorough. Ask follow-ups.""",
            'hard': """You are a rigorous AI interviewer. Be challenging but fair."""
        }
    }

@app.route('/interview_stream', methods=['POST'])
def interview_stream():
    data = request.json
    user_message = data.get('message', '')
    difficulty = data.get('difficulty', 'medium')
    
    if 'conversation' not in session:
        session['conversation'] = []
        session['interview_type'] = 'general'
        session['difficulty'] = difficulty
    
    # Detect interview type from first message
    if len(session['conversation']) == 0:
        lower_msg = user_message.lower()
        if 'coding' in lower_msg:
            session['interview_type'] = 'coding'
        elif 'behavioral' in lower_msg:
            session['interview_type'] = 'behavioral'
        elif 'system design' in lower_msg:
            session['interview_type'] = 'system design'
    
    session['conversation'].append({
        "role": "user",
        "content": user_message
    })
    
    interview_type = session.get('interview_type', 'general')
    current_difficulty = session.get('difficulty', 'medium')
    
    system_prompts = get_system_prompts()
    system_prompt = system_prompts.get(interview_type, {}).get(current_difficulty, 
                    system_prompts['general']['medium'])
    
    messages = [
        {"role": "system", "content": system_prompt}
    ] + session['conversation']
    
    def generate():
        try:
            stream = client.chat.completions.create(
                messages=messages,
                model="llama-3.3-70b-versatile",
                temperature=0.8,
                max_tokens=2500,
                stream=True
            )
            
            full_response = ""
            import time
            
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    full_response += content
                    
                    # Add small delay for natural typing effect
                    time.sleep(0.02)  # 20ms delay per chunk
                    
                    yield f"data: {json.dumps({'content': content})}\n\n"
            
            # Save to session after stream completes
            session['conversation'].append({
                "role": "assistant",
                "content": full_response
            })
            
            if len(session['conversation']) > 30:
                session['conversation'] = session['conversation'][-30:]
            
            session.modified = True
            
            yield f"data: {json.dumps({'done': True})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/save_interview', methods=['POST'])
def save_interview():
    try:
        data = request.json
        rating = data.get('rating', 0)
        
        start_time_str = session.get('start_time')
        if start_time_str:
            start_time = datetime.fromisoformat(start_time_str)
            duration = int((datetime.now() - start_time).total_seconds())
        else:
            duration = 0
        
        conn = sqlite3.connect('interviews.db')
        c = conn.cursor()
        # Auto-generate smart title from conversation
        conversation = session.get('conversation', [])
        smart_title = generate_interview_title(conversation, session.get('interview_type', 'general'))

        c.execute('''INSERT INTO interviews 
                     (session_id, user_id, interview_type, difficulty, timestamp, messages, rating, duration, message_count, title)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (session.get('session_id'),
                   session.get('user_id', None),
                   session.get('interview_type', 'general'),
                   session.get('difficulty', 'medium'),
                   datetime.now().isoformat(),
                   json.dumps(conversation),
                   rating,
                   duration,
                   len(conversation) // 2,
                   smart_title))
        
        interview_id = c.lastrowid
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'interview_id': interview_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get_history', methods=['GET'])
def get_history():
    try:
        conn = sqlite3.connect('interviews.db')
        c = conn.cursor()
        user_id = session.get('user_id', None)
        if user_id:
            c.execute('''SELECT id, interview_type, difficulty, timestamp, rating, duration, message_count, title
                     FROM interviews WHERE user_id = ?
                     ORDER BY timestamp DESC LIMIT 20''', (user_id,))
        else:
            c.execute('''SELECT id, interview_type, difficulty, timestamp, rating, duration, message_count
                     FROM interviews WHERE session_id = ?
                     ORDER BY timestamp DESC LIMIT 20''', (session.get('session_id'),))
        
        rows = c.fetchall()
        conn.close()
        
        history = []
        for row in rows:
            history.append({
                'id': row[0],
                'type': row[1],
                'difficulty': row[2],
                'date': row[3],
                'rating': row[4],
                'duration': row[5],
                'message_count': row[6],
                'title': row[7] if row[7] else f"{row[1].title()} Interview"
            })
        
        return jsonify({'history': history})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_interview/<int:interview_id>', methods=['GET'])
def get_interview(interview_id):
    try:
        conn = sqlite3.connect('interviews.db')
        c = conn.cursor()
        c.execute('SELECT messages, interview_type, difficulty, timestamp FROM interviews WHERE id = ?', 
                  (interview_id,))
        row = c.fetchone()
        conn.close()
        
        if row:
            return jsonify({
                'messages': json.loads(row[0]),
                'type': row[1],
                'difficulty': row[2],
                'timestamp': row[3]
            })
        else:
            return jsonify({'error': 'Interview not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/export_transcript', methods=['POST'])
def export_transcript():
    try:
        conversation = session.get('conversation', [])
        
        transcript = f"InterviewIQ - Interview Transcript\n"
        transcript += f"{'=' * 60}\n\n"
        transcript += f"Date: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}\n"
        transcript += f"Type: {session.get('interview_type', 'general').title()}\n"
        transcript += f"Difficulty: {session.get('difficulty', 'medium').title()}\n"
        transcript += f"Total Messages: {len(conversation)}\n"
        transcript += f"\n{'=' * 60}\n\n"
        
        for i, msg in enumerate(conversation, 1):
            role = "You" if msg['role'] == 'user' else "Interviewer"
            transcript += f"{role}:\n{msg['content']}\n\n"
            transcript += f"{'-' * 60}\n\n"
        
        file_obj = io.BytesIO()
        file_obj.write(transcript.encode('utf-8'))
        file_obj.seek(0)
        
        filename = f"interview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        return send_file(
            file_obj,
            mimetype='text/plain',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/analytics', methods=['GET'])
def analytics():
    try:
        conn = sqlite3.connect('interviews.db')
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM interviews')
        total = c.fetchone()[0]
        
        c.execute('SELECT interview_type, COUNT(*) FROM interviews GROUP BY interview_type')
        by_type = {row[0]: row[1] for row in c.fetchall()}
        
        c.execute('SELECT difficulty, COUNT(*) FROM interviews GROUP BY difficulty')
        by_difficulty = {row[0]: row[1] for row in c.fetchall()}
        
        c.execute('SELECT AVG(rating) FROM interviews WHERE rating > 0')
        avg_rating = c.fetchone()[0] or 0
        
        c.execute('SELECT SUM(duration) FROM interviews')
        total_time = c.fetchone()[0] or 0
        
        c.execute('SELECT AVG(duration) FROM interviews')
        avg_duration = c.fetchone()[0] or 0
        
        conn.close()
        
        return jsonify({
            'total_interviews': max(total, int(os.environ.get('MIN_INTERVIEWS', 0))),
            'by_type': by_type,
            'by_difficulty': by_difficulty,
            'avg_rating': round(avg_rating, 2) if avg_rating and avg_rating > 0 else 0,
            'total_time_minutes': round(total_time / 60, 1),
            'avg_duration_minutes': round(avg_duration / 60, 1),
            'total_users': int(os.environ.get('MIN_USERS', 0))
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/set_difficulty', methods=['POST'])
def set_difficulty():
    data = request.json
    difficulty = data.get('difficulty', 'medium')
    session['difficulty'] = difficulty
    session.modified = True
    return jsonify({'success': True})

if __name__ == '__main__':
    import os
    import threading
    import requests
    import time

    def keep_alive():
        while True:
            time.sleep(600)  # every 10 minutes
            try:
                url = os.environ.get('RENDER_EXTERNAL_URL', 'https://interviewiq-83bs.onrender.com')
                requests.get(url)
                print("Keep-alive ping sent")
            except:
                pass

    t = threading.Thread(target=keep_alive, daemon=True)
    t.start()

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)