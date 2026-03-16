from flask import Flask, render_template, request, jsonify, session
from dotenv import load_dotenv
import os
from groq import Groq

# Load environment variables
load_dotenv()

# TODO for v2.0:
# - Add user authentication so people can save their practice sessions
# - Track performance over time (how many questions answered correctly)
# - Maybe add voice mode? Would be cool to practice speaking answers out loud
# - Add a timer for each question (simulate real interview pressure)

app = Flask(__name__)

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(24)  # needed for session management

# Configure Groq
client = Groq(api_key=os.getenv('GROQ_API_KEY'))

@app.route('/')
def home():
    # Clear conversation history when page loads
    session.clear()
    return render_template('index.html')

@app.route('/interview', methods=['POST'])
def interview():
    data = request.json
    user_message = data.get('message', '')
    
    # Get or initialize conversation history
    if 'conversation' not in session:
        session['conversation'] = []
    
    # Add user message to history
    session['conversation'].append({
        "role": "user",
        "content": user_message
    })
    
    # Prepare messages for API (system prompt + conversation history)
    messages = [
        {
            "role": "system",
            "content": "You are an AI interviewer conducting technical interviews. Ask coding questions, give feedback, and have conversations about technical topics. Remember previous parts of the conversation."
        }
    ] + session['conversation']
    
    # Call Groq API with full conversation context
    chat_completion = client.chat.completions.create(
        messages=messages,
        model="llama-3.3-70b-versatile",
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

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)