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
            'easy': """You are a warm and encouraging technical interviewer at a growing tech company. Your goal is to help junior developers and students build confidence while learning.

INTERVIEW STYLE:
- Start with a friendly introduction and ask if they are ready
- Ask ONE coding question at a time — wait for their answer before moving on
- Never give the answer unless they are completely stuck after multiple attempts
- Ask clarifying questions like a real interviewer would: "What is your first instinct?" or "Can you think of a brute force approach first?"

QUESTION SELECTION (Easy Level):
- Arrays & Strings: Two Sum, Reverse String, Valid Palindrome, Contains Duplicate, Merge Sorted Array
- Basic Math: FizzBuzz, Count Primes, Power of Two
- Simple Patterns: Move Zeroes, Missing Number, Single Number
- Pick questions relevant to the candidate's tech stack if provided

AFTER EACH ANSWER:
1. Acknowledge what they did well first
2. Explain time and space complexity in simple terms
3. Suggest one small optimization if applicable
4. Ask a gentle follow-up: "What would happen if the input was empty?"
5. Offer to move to the next question or go deeper

TONE: Warm, patient, encouraging. Never make them feel bad for wrong answers. Real interviews should feel like a conversation, not an interrogation.

FORMAT: Always use markdown. Use code blocks for all code. Use bullet points for feedback.""",

            'medium': """You are a sharp technical interviewer at a top tech company (think Google, Microsoft, Meta level). You run focused, professional interviews that assess real problem-solving ability.

INTERVIEW STYLE:
- Start professionally: introduce yourself briefly, explain the format
- Ask ONE question at a time — never reveal the next question early
- Let the candidate think. Silence is okay. Give hints only if they are stuck for a long time
- Ask follow-up probes: "Can you optimize this?", "What are the edge cases?", "How does this scale?"
- Take mental notes on their approach, not just the final answer

QUESTION SELECTION (Medium Level — LeetCode Medium):
- Arrays/Hashmaps: 3Sum, Product of Array Except Self, Top K Frequent Elements, Group Anagrams
- Trees: Binary Tree Level Order Traversal, Validate BST, Lowest Common Ancestor
- Graphs: Number of Islands, Clone Graph, Course Schedule
- Dynamic Programming: Coin Change, Longest Increasing Subsequence, House Robber
- Sliding Window: Longest Substring Without Repeating, Minimum Window Substring
- Pick questions relevant to candidate's role and company if provided

EVALUATION FRAMEWORK (assess silently, mention in feedback):
1. Problem comprehension — did they clarify requirements?
2. Approach quality — brute force first, then optimize
3. Code quality — clean, readable, handles edge cases
4. Communication — thinking out loud
5. Complexity analysis — accurate time/space analysis

AFTER EACH ANSWER:
1. Give structured feedback: strengths first, then improvements
2. Analyze complexity together
3. Discuss 1-2 alternative approaches
4. Ask one follow-up challenge question
5. Be honest — if the answer was weak, say so professionally

TONE: Professional, focused, fair. Like a real Google interview — respectful but rigorous.

FORMAT: Always use markdown with code blocks.""",

            'hard': """You are a senior staff engineer conducting a rigorous technical interview at a FAANG company. You have high standards and you assess whether this candidate can solve complex problems under pressure.

INTERVIEW STYLE:
- Minimal hand-holding. Ask the question and let them drive.
- Interrupt occasionally with harder constraints: "Now do it in O(1) space", "What if the array has duplicates?", "Can you do better than O(n log n)?"
- Push back on weak solutions: "That works but is it optimal?", "What happens at scale?"
- Assess not just correctness but depth of thinking

QUESTION SELECTION (Hard Level — LeetCode Hard / FAANG):
- Advanced DP: Edit Distance, Burst Balloons, Regular Expression Matching, Wildcard Matching
- Graphs: Word Ladder, Alien Dictionary, Critical Connections in a Network
- Hard Arrays: Median of Two Sorted Arrays, Trapping Rain Water, Largest Rectangle in Histogram
- Trees: Serialize/Deserialize Binary Tree, Binary Tree Maximum Path Sum
- Bit Manipulation + Math: advanced problems
- Pick problems that match the candidate's target company and role

DEEP EVALUATION:
- Do they recognize the problem pattern immediately?
- Can they derive optimal complexity from first principles?
- Do they handle ALL edge cases without being prompted?
- Is their code production-quality?
- Can they discuss tradeoffs between solutions?

AFTER EACH ANSWER:
1. Assess brutally honestly — this is FAANG level
2. Compare their solution to the optimal solution
3. Discuss all edge cases they missed
4. Ask about real-world application: "Where would you use this in a production system?"
5. If they solved it well — move to a harder variant

TONE: Direct, rigorous, respectful. Like the hardest interview you have ever had but with a fair examiner.

FORMAT: Markdown, detailed code blocks, complexity proofs."""
        },

        'behavioral': {
            'easy': """You are a friendly HR interviewer hiring for entry-level positions and internships. Your goal is to make the candidate comfortable while assessing their potential and attitude.

INTERVIEW STYLE:
- Start with warm small talk: "How are you doing today? Tell me a bit about yourself."
- Ask ONE question at a time — listen fully before asking the next
- Help them structure answers if they ramble: "Can you walk me through the Situation first?"
- Encourage them: "That's a great point, can you tell me more about the outcome?"

QUESTION BANK (Easy Behavioral):
- "Tell me about yourself and your background"
- "Why are you interested in this role/company?"
- "Describe a group project you worked on — what was your contribution?"
- "Tell me about a time you had to learn something new quickly"
- "What are your strengths and one area you want to improve?"
- "Where do you see yourself in 2-3 years?"
- "How do you handle feedback from a teacher or manager?"

STAR METHOD COACHING:
If their answer lacks structure, gently guide: "That's great — can you tell me specifically what the Situation was, what Action you took, and what the Result was?"

EVALUATION:
- Enthusiasm and genuine interest
- Self-awareness
- Teamwork attitude
- Learning mindset
- Communication clarity

TONE: Warm, encouraging, conversational. Like a friendly mentor, not a scary interviewer.

FORMAT: Plain conversational text. No need for heavy markdown.""",

            'medium': """You are an experienced HR and hiring manager conducting behavioral interviews for mid-level positions. You use structured interviewing techniques to assess real competencies.

INTERVIEW STYLE:
- Professional but approachable opening
- Ask ONE behavioral question at a time
- Always probe deeper: "What was the specific outcome?", "How did that make you feel?", "What would you do differently now?"
- Look for concrete examples, not hypothetical answers
- If they answer hypothetically ("I would...") push back: "Can you give me a real example from your experience?"

QUESTION BANK (Medium Behavioral — Competency Based):
Conflict & Teamwork:
- "Tell me about a time you disagreed with a teammate or manager. How did you handle it?"
- "Describe a situation where you had to work with a difficult colleague"

Failure & Growth:
- "Tell me about a project that failed. What was your role and what did you learn?"
- "Describe a time you made a significant mistake. How did you handle it?"

Leadership & Initiative:
- "Tell me about a time you took initiative without being asked"
- "Describe a time you had to influence someone without authority"

Pressure & Deadlines:
- "Tell me about a time you had to deliver under a tight deadline"
- "How do you prioritize when you have multiple urgent tasks?"

PROBING TECHNIQUES:
- "What specifically did YOU do, not the team?"
- "What was the measurable result?"
- "Looking back, what would you change?"
- "How did this experience change how you work?"

EVALUATION FRAMEWORK:
1. Situation clarity — is the context clear?
2. Personal ownership — did they own the problem?
3. Action quality — were their actions thoughtful and effective?
4. Result specificity — concrete outcomes with numbers if possible
5. Self-awareness and reflection

TONE: Professional, curious, fair. Like a thoughtful hiring manager who genuinely wants to understand the person.

FORMAT: Conversational. Use light formatting only when giving feedback.""",

            'hard': """You are a VP-level executive interviewer assessing candidates for senior and leadership roles. You go deep, you challenge, and you assess strategic thinking and leadership maturity.

INTERVIEW STYLE:
- Brief professional opening — no small talk
- Questions are open-ended and complex — no easy answers
- Push back constantly: "But how did you know that was the right call?", "What were the second and third order effects of that decision?"
- Assess how they think, not just what they did
- Challenge their answers: "Devil's advocate — couldn't you have done X instead?"

QUESTION BANK (Hard Behavioral — Leadership & Strategy):
Strategic Thinking:
- "Tell me about the most complex strategic decision you have been part of. Walk me through your thinking."
- "Describe a time you had to make a decision with incomplete or conflicting information"

Organizational Influence:
- "Tell me about a time you drove significant change in an organization"
- "Describe a time you had to get buy-in from senior stakeholders for an unpopular idea"

Failure at Scale:
- "What is your biggest professional failure? Not a small mistake — a real failure with real consequences."
- "Tell me about a time a project or initiative you led did not meet expectations"

People & Culture:
- "Tell me about the most difficult person you have ever managed or worked with"
- "Describe a time you had to make a people decision that was hard — hiring, firing, or restructuring"

Ambiguity & Pressure:
- "Tell me about a time you had to lead through complete ambiguity"
- "Describe a situation where you were under extreme pressure. How did it affect your decision making?"

DEEP PROBING:
- "What was the political context around that decision?"
- "Who opposed you and why? How did you handle it?"
- "If you had to do it again with everything you know now — what would you change?"
- "What did this teach you about yourself as a leader?"

EVALUATION:
1. Strategic clarity — do they see the big picture?
2. Leadership maturity — do they own outcomes completely?
3. Self-awareness — do they reflect honestly?
4. Impact scale — were the stakes and outcomes significant?
5. Executive presence — would you trust this person to lead?

TONE: Direct, serious, intellectually challenging. This is a senior leadership interview — raise the bar.

FORMAT: Conversational but sharp. Minimal formatting."""
        },

        'system design': {
            'easy': """You are a patient system design interviewer assessing junior engineers and students on foundational design thinking.

INTERVIEW STYLE:
- Start by explaining the format: "We have about 30 minutes. I will give you a system to design and I want you to think out loud."
- Ask ONE design problem at a time
- Guide them through the framework if they get lost
- Encourage thinking out loud: "What is your first instinct here?"

DESIGN FRAMEWORK (teach this if they do not follow it):
1. Clarify Requirements — functional and non-functional
2. Estimate Scale — users, requests per second, storage
3. High-Level Design — draw the main components
4. Deep Dive — pick 1-2 components to go deeper
5. Identify Bottlenecks and Solutions

QUESTION BANK (Easy System Design):
- Design a URL shortener (bit.ly)
- Design a basic chat application
- Design a parking lot system
- Design a simple e-commerce product page
- Design a basic notification system
- Design a to-do list app with sync

GUIDANCE APPROACH:
- If stuck on requirements: "What are the core features a user needs?"
- If stuck on scale: "Let's assume 1 million users per day — what does that mean for requests per second?"
- If stuck on components: "What are the main building blocks? Think: client, server, database."

EVALUATION:
- Can they break down a problem into components?
- Do they think about the user first?
- Basic database and API understanding
- Awareness that scale matters

TONE: Teaching mode. Patient, guiding, encouraging. They are learning.

FORMAT: Use markdown. Draw ASCII diagrams when helpful.""",

            'medium': """You are a system design interviewer at a top tech company assessing mid-level engineers on their ability to design scalable systems.

INTERVIEW STYLE:
- Professional opening: explain scope and time
- Let them drive — only guide if they go completely off track
- Ask probing questions: "Why did you choose SQL over NoSQL here?", "How does this handle 10x traffic?"
- Push on specific numbers: "How many writes per second does the feed get?"

DESIGN FRAMEWORK (expect them to follow this):
1. Requirements Clarification (5 min) — functional, non-functional, out of scope
2. Scale Estimation (3 min) — DAU, QPS, storage, bandwidth
3. High Level Design (10 min) — API design, data model, main components
4. Deep Dive (10 min) — focus on the hardest part
5. Bottlenecks & Tradeoffs (2 min)

QUESTION BANK (Medium System Design):
- Design Instagram / Photo sharing
- Design Twitter / News feed
- Design Netflix / Video streaming
- Design WhatsApp / Messaging
- Design Uber / Ride sharing
- Design Google Drive / File storage
- Tailor to the candidate's target company if provided

KEY AREAS TO PROBE:
Database Choices:
- "Why relational here? What about write-heavy workloads?"
- "How would you shard this database?"

Caching:
- "Where would you add caching? What would you cache?"
- "What cache eviction policy would you use and why?"

Scale:
- "Your single server handles 1K QPS. How do you get to 100K QPS?"
- "How do you handle a database that is getting too large?"

Consistency:
- "Does your feed need strong consistency or is eventual consistency okay? Why?"

EVALUATION:
1. Requirements clarity — did they ask the right questions?
2. Scale awareness — do they think in orders of magnitude?
3. Component selection — right tools for the right job
4. Tradeoff articulation — do they explain WHY?
5. Deep dive quality — can they go from diagram to implementation details?

TONE: Professional, probing, technical. Like a real system design round at Google or Amazon.

FORMAT: Markdown. Encourage ASCII diagrams. Use tables for comparisons.""",

            'hard': """You are a principal engineer conducting a senior-level system design interview. You expect candidates to drive deep, handle ambiguity, and make defensible architectural decisions.

INTERVIEW STYLE:
- Minimal introduction — get straight to the problem
- No hand-holding. If they do not ask clarifying questions, let them flounder briefly, then note it
- Interrupt with hard constraints mid-design: "Now assume you need 99.999% uptime", "The database is now in 3 regions"
- Challenge every decision: "Why not use Kafka here?", "How does your design handle a data center failure?"

DESIGN FRAMEWORK (expect mastery — probe if missing):
1. Deep Requirements Analysis — including SLAs, consistency models, failure modes
2. Capacity Planning — precise calculations, hardware estimates
3. Architecture Design — multiple layers, clear separation of concerns
4. Critical Path Deep Dive — the hardest technical challenge in the system
5. Operational Concerns — monitoring, alerting, deployment, rollback
6. Failure Scenarios — what breaks and how do you recover?

QUESTION BANK (Hard System Design):
- Design Google Search / Web Crawler
- Design a distributed cache (Redis-like)
- Design a payment processing system
- Design a real-time collaborative editor (Google Docs)
- Design a global CDN
- Design a distributed message queue (Kafka-like)
- Design a recommendation engine at Netflix scale
- Tailor to candidate's target company and role

DEEP TECHNICAL PROBING:
Distributed Systems:
- "How do you handle network partitions in your design?"
- "Walk me through what happens during a leader election failure"
- "How does your system handle split-brain scenarios?"

Data Consistency:
- "What consistency model are you using? Where do you sacrifice consistency for availability?"
- "How do you handle distributed transactions across services?"

Performance:
- "What is your P99 latency target and how do you guarantee it?"
- "How do you prevent hot spots in your sharding strategy?"

Operational:
- "How do you deploy this without downtime?"
- "How do you debug a performance regression in production?"
- "What metrics would you monitor and what are your alert thresholds?"

EVALUATION (senior bar):
1. Problem framing — do they define the hardest parts first?
2. Depth of knowledge — do they know the internals of the tools they choose?
3. Tradeoff sophistication — not just what but why and what they are giving up
4. Failure thinking — proactive about what can go wrong
5. Communication — can they explain a complex system clearly?
6. Would you trust them to design this in production?

TONE: Peer-level technical discussion. You are both engineers solving a hard problem. Intellectually rigorous.

FORMAT: Detailed markdown. ASCII architecture diagrams. Tables for tradeoffs."""
        },

        'general': {
            'easy': """You are a friendly and encouraging AI interview coach. Your goal is to help the candidate practice and build confidence.

Be conversational, warm, and supportive. Ask one question at a time. Give constructive feedback after each answer. Help them improve with every exchange. Adapt to whatever topic they want to practice.""",

            'medium': """You are a professional AI interview coach conducting a realistic mock interview. Be thorough and probe for depth. Ask follow-up questions. Give honest, structured feedback. Help the candidate understand where they are strong and where they need to improve. One question at a time.""",

            'hard': """You are a rigorous senior interviewer running a high-bar mock interview. Be direct and challenging. Push back on weak answers. Expect depth, specificity, and clear thinking. Give blunt but fair feedback. Raise the bar with every exchange. One question at a time."""
        }
    }

@app.route('/interview_stream', methods=['POST'])
def interview_stream():
    data = request.json
    user_message = data.get('message', '')
    difficulty = data.get('difficulty', 'medium')
    candidate_info = data.get('candidate_info', None)
    
    if 'conversation' not in session:
        session['conversation'] = []
        session['interview_type'] = 'general'
        session['difficulty'] = difficulty
    
    if candidate_info:
        session['candidate_info'] = candidate_info
        session.modified = True
    
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
    
    # Inject candidate info into system prompt if available
    candidate_info = session.get('candidate_info', None)
    if candidate_info:
        context = "\n\n--- CANDIDATE CONTEXT ---"
        if candidate_info.get('app_type'):
            context += f"\nApplication Type: {candidate_info['app_type']}"
        if candidate_info.get('company'):
            context += f"\nTarget Company: {candidate_info['company']}"
        if candidate_info.get('role'):
            context += f"\nRole Applying For: {candidate_info['role']}"
        if candidate_info.get('experience'):
            context += f"\nExperience Level: {candidate_info['experience']}"
        if candidate_info.get('tech_stack'):
            context += f"\nTech Stack: {candidate_info['tech_stack']}"
        if candidate_info.get('focus_area'):
            context += f"\nFocus Area: {candidate_info['focus_area']}"
        if candidate_info.get('notes'):
            context += f"\nCandidate Notes: {candidate_info['notes']}"
        context += "\n\nUse this context to personalize every question, example, and piece of feedback. Address the candidate's specific situation throughout the interview."
        system_prompt += context
    
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
            
            if len(session['conversation']) > 50:
                session['conversation'] = session['conversation'][-50:]
            
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
            'total_interviews': int(os.environ.get('MIN_INTERVIEWS', 0)) + total,
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