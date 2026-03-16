from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import os
from groq import Groq

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configure Groq
client = Groq(api_key=os.getenv('GROQ_API_KEY'))

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/interview', methods=['POST'])
def interview():
    data = request.json
    user_message = data.get('message', '')
    
    # Call Groq API
    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": "You are an AI interviewer conducting technical interviews. Ask coding questions, give feedback, and have conversations about technical topics."
            },
            {
                "role": "user",
                "content": user_message
            }
        ],
        model="llama-3.3-70b-versatile",
    )
    
    return jsonify({'response': chat_completion.choices[0].message.content})

if __name__ == '__main__':
    app.run(debug=True)