from flask import Flask, render_template, request, jsonify, session, send_file
from dotenv import load_dotenv
import os
from groq import Groq
import sqlite3
from datetime import datetime
import json

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configure Groq
client = Groq(api_key=os.getenv('GROQ_API_KEY'))

# Database setup
def init_db():
    conn = sqlite3.connect('interviews.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS interviews
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT,
                  interview_type TEXT,
                  timestamp TEXT,
                  messages TEXT,
                  rating INTEGER)''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def home():
    # Generate unique session ID
    if 'session_id' not in session:
        session['session_id'] = os.urandom(16).hex()
    session.clear()
    session['session_id'] = os.urandom(16).hex()
    return render_template('index.html')

@app.route('/interview', methods=['POST'])
def interview():
    data = request.json
    user_message = data.get('message', '')
    
    # Get or initialize conversation history
    if 'conversation' not in session:
        session['conversation'] = []
        session['interview_type'] = 'general'
    
    # Detect interview type from first message
    if len(session['conversation']) == 0:
        lower_msg = user_message.lower()
        if 'coding' in lower_msg:
            session['interview_type'] = 'coding'
        elif 'behavioral' in lower_msg:
            session['interview_type'] = 'behavioral'
        elif 'system design' in lower_msg:
            session['interview_type'] = 'system design'
    
    # Add user message to history
    session['conversation'].append({
        "role": "user",
        "content": user_message
    })
    
    # Enhanced system prompts based on interview type
    system_prompts = {
        'coding': """You are an expert technical interviewer at a top tech company (Google, Meta, Amazon level).

Your role:
- Ask ONE coding question at a time
- Start with easier problems, increase difficulty based on performance
- After the candidate answers, give detailed feedback on:
  * Time complexity
  * Space complexity  
  * Code quality and best practices
  * Edge cases they missed
  * Better approaches if any exist
- Ask clarifying questions about their solution
- Be encouraging but honest
- Use markdown formatting with code blocks

Example response format:
"Great! Let me give you a problem:

**Problem**: [Clear problem statement]
```
Example:
Input: [example]
Output: [example]
```

Take your time to think through the approach before coding."
""",
        'behavioral': """You are an experienced HR interviewer conducting behavioral interviews for senior positions.

Your role:
- Ask ONE behavioral question at a time using STAR method
- Focus on: leadership, conflict resolution, teamwork, problem-solving
- Listen for specific examples, not generic answers
- Probe deeper with follow-up questions like "Can you tell me more about..." or "What was the outcome?"
- Give constructive feedback on their answers
- Be warm and encouraging

Questions should assess real experience, not theoretical knowledge.""",
        
        'system design': """You are a senior architect interviewing candidates for system design skills.

Your role:
- Ask ONE system design question at a time
- Start with requirements gathering (scale, features, constraints)
- Guide them through: high-level design → detailed design → tradeoffs
- Discuss: scalability, reliability, data storage, APIs, caching, load balancing
- Ask about edge cases and failure scenarios
- Give feedback on their architectural choices

Example flow:
1. "Design Instagram's feed" 
2. Ask about scale (DAU, posts/day)
3. Discuss components (API gateway, databases, CDN, etc.)
4. Deep dive into specific areas""",
        
        'general': """You are a friendly AI interviewer helping people practice technical interviews.

Be conversational, helpful, and adjust to what they want to practice."""
    }
    
    interview_type = session.get('interview_type', 'general')
    system_prompt = system_prompts.get(interview_type, system_prompts['general'])
    
    # Prepare messages for API
    messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ] + session['conversation']
    
    # Call Groq API with conversation context
    try:
        chat_completion = client.chat.completions.create(
            messages=messages,
            model="llama-3.3-70b-versatile",
            temperature=0.7,
            max_tokens=2000
        )
        
        ai_response = chat_completion.choices[0].message.content
        
        # Add AI response to history
        session['conversation'].append({
            "role": "assistant",
            "content": ai_response
        })
        
        # Keep conversation from getting too long (last 20 messages)
        # NOTE: Had this at 10 before but was cutting off context too early
        if len(session['conversation']) > 20:
            session['conversation'] = session['conversation'][-20:]
        
        session.modified = True
        
        return jsonify({'response': ai_response})
        
    except Exception as e:
        return jsonify({'response': f'Error: {str(e)}'}), 500

@app.route('/save_interview', methods=['POST'])
def save_interview():
    """Save interview to database"""
    try:
        data = request.json
        
        conn = sqlite3.connect('interviews.db')
        c = conn.cursor()
        c.execute('''INSERT INTO interviews 
                     (session_id, interview_type, timestamp, messages, rating)
                     VALUES (?, ?, ?, ?, ?)''',
                  (session.get('session_id'),
                   session.get('interview_type', 'general'),
                   datetime.now().isoformat(),
                   json.dumps(session.get('conversation', [])),
                   data.get('rating', 0)))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get_history', methods=['GET'])
def get_history():
    """Get interview history"""
    try:
        conn = sqlite3.connect('interviews.db')
        c = conn.cursor()
        c.execute('''SELECT id, interview_type, timestamp, rating 
                     FROM interviews 
                     ORDER BY timestamp DESC 
                     LIMIT 10''')
        
        rows = c.fetchall()
        conn.close()
        
        history = []
        for row in rows:
            history.append({
                'id': row[0],
                'type': row[1],
                'date': row[2],
                'rating': row[3]
            })
        
        return jsonify({'history': history})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_interview/<int:interview_id>', methods=['GET'])
def get_interview(interview_id):
    """Get specific interview details"""
    try:
        conn = sqlite3.connect('interviews.db')
        c = conn.cursor()
        c.execute('SELECT messages FROM interviews WHERE id = ?', (interview_id,))
        row = c.fetchone()
        conn.close()
        
        if row:
            messages = json.loads(row[0])
            return jsonify({'messages': messages})
        else:
            return jsonify({'error': 'Interview not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/export_transcript', methods=['POST'])
def export_transcript():
    """Export current interview as text file"""
    try:
        conversation = session.get('conversation', [])
        
        # Create transcript
        transcript = f"InterviewIQ - Interview Transcript\n"
        transcript += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        transcript += f"Type: {session.get('interview_type', 'general').title()}\n"
        transcript += "=" * 50 + "\n\n"
        
        for msg in conversation:
            role = "You" if msg['role'] == 'user' else "Interviewer"
            transcript += f"{role}:\n{msg['content']}\n\n"
        
        # Save to file
        filename = f"interview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        filepath = os.path.join('/tmp', filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(transcript)
        
        return send_file(filepath, as_attachment=True, download_name=filename)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/analytics', methods=['GET'])
def analytics():
    """Get analytics data"""
    try:
        conn = sqlite3.connect('interviews.db')
        c = conn.cursor()
        
        # Total interviews
        c.execute('SELECT COUNT(*) FROM interviews')
        total = c.fetchone()[0]
        
        # By type
        c.execute('SELECT interview_type, COUNT(*) FROM interviews GROUP BY interview_type')
        by_type = dict(c.fetchall())
        
        # Average rating
        c.execute('SELECT AVG(rating) FROM interviews WHERE rating > 0')
        avg_rating = c.fetchone()[0] or 0
        
        conn.close()
        
        return jsonify({
            'total_interviews': total,
            'by_type': by_type,
            'avg_rating': round(avg_rating, 2)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)