# This was my first attempt using Anthropic's Claude API
# Didn't work because I didn't realize API credits were separate from Pro subscription
# Keeping this here in case I want to switch back later

from anthropic import Anthropic
import os

# This failed with "credit balance too low" error
# client = Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

# Switched to Groq instead - works better anyway