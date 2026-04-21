🚀 **Live Demo:** [https://interviewiq-mjeh.onrender.com](https://interviewiq-mjeh.onrender.com)
# InterviewIQ

Mock interview practice tool with AI. Built this because I got tired of bugging my friends to do practice interviews with me.

## What it does

Pretty simple - you chat with an AI that acts like an interviewer. It asks coding questions, follows up on your answers, and you can practice explaining your thought process.

## Running it locally
```bash
pip install -r requirements.txt
python main.py
```

You'll need a Groq API key in a `.env` file:
```
GROQ_API_KEY=your_key_here
```

Get one free at https://console.groq.com

## Tech

- Flask for the backend
- Groq API (Llama 3.3 model) 
- Basic HTML/CSS/JS frontend

Originally tried using Google's Gemini but kept hitting rate limits. Groq has been more reliable.

## What's next

Right now it's pretty basic - just one message at a time, no memory of the conversation. Planning to add:

- Conversation history so it actually remembers what you said
- Different interview modes (behavioral, system design, etc)
- Maybe save past sessions so you can see your progress

For now it works well enough for quick practice sessions.