from dotenv import load_dotenv
import os
import requests
import json

load_dotenv()

class ModelGateway:
    CONFIGS = {
        "OpenAI": {
            "api_key_env": "OPENAI_API_KEY",
            "url": "https://api.openai.com/v1/chat/completions",
            "headers_fn": lambda key: {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
        },
        "OpenRouter": {
            "api_key_env": "OPENROUTER_API_KEY",
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "headers_fn": lambda key: {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/cli-chatbot",
                "X-Title": "CLI Chatbot"
            }
        },
        "Groq": {
            "api_key_env": "GROQ_API_KEY",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "headers_fn": lambda key: {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            }
        },
        "Google Gemini (OpenAI Compatible)": {
            "api_key_env": "GOOGLE_API_KEY",
            "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "headers_fn": lambda key: {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
        }
    }

    PROVIDERS = {
        "OpenAI": {
            "api_key_env": "OPENAI_API_KEY",
            "url": "https://api.openai.com/v1/models",
            "headers_fn": lambda key: {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
        },
        "OpenRouter": {
            "api_key_env": "OPENROUTER_API_KEY",
            "url": "https://openrouter.ai/api/v1/models",
            "headers_fn": lambda key: {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
        },
        "Groq": {
            "api_key_env": "GROQ_API_KEY",
            "url": "https://api.groq.com/openai/v1/models",
            "headers_fn": lambda key: {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            }
        },
        "Google Gemini (OpenAI Compatible)": {
            "api_key_env": "GOOGLE_API_KEY",
            "url": "https://generativelanguage.googleapis.com/v1beta/openai/models",
            "headers_fn": lambda key: {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }
        }
    }

    def _get_api_key(self, provider_name, mapping):
        env_var = mapping[provider_name]["api_key_env"]
        return os.environ.get(env_var)

    def list_models(self):
        all_models = {}
        for name, config in self.PROVIDERS.items():
            key = self._get_api_key(name, self.PROVIDERS)
            if not key:
                continue
            
            try:
                response = requests.get(config["url"], headers=config["headers_fn"](key))
                if response.status_code == 200:
                    all_models[name] = response.json()
            except Exception as e:
                print(f"Error fetching models from {name}: {e}")
        return all_models

    def generate(self, provider_name, model, messages, temperature=0.7, tools=None):
        if provider_name not in self.CONFIGS:
            raise ValueError(f"Provider {provider_name} not supported.")
        
        config = self.CONFIGS[provider_name]
        key = self._get_api_key(provider_name, self.CONFIGS)
        
        if not key:
            raise ValueError(f"API Key for {provider_name} not found in environment.")

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature
        }
        
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        
        response = requests.post(
            config["url"], 
            headers=config["headers_fn"](key), 
            json=payload
        )
        
        response.raise_for_status()
        return response.json()
