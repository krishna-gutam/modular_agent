from dotenv import load_dotenv
import os
import json
import urllib.request

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



    def fetch_models(self, provider_name, config):
        api_key = os.getenv(config["api_key_env"])
        if not api_key:
            return None

        headers = config["headers_fn"](api_key)
        req = urllib.request.Request(config["url"], headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                data = json.loads(response.read().decode("utf-8"))
                
                models_list = []
                if isinstance(data, dict):
                    if "data" in data and isinstance(data["data"], list):
                        models_list = data["data"]
                    elif "models" in data and isinstance(data["models"], list):
                        models_list = data["models"]
                elif isinstance(data, list):
                    models_list = data

                clean_models = []
                for m in models_list:
                    if isinstance(m, dict):
                        model_id = m.get("id") or m.get("name") or str(m)
                    else:
                        model_id = str(m)
                    clean_models.append(model_id)
                return clean_models

        except Exception:
            return None

    def list_models(self):
        all_discovered = {}
        
        for provider_name, config in self.PROVIDERS.items():
            models = self.fetch_models(provider_name, config)
            if models is not None:
                all_discovered[provider_name] = models

        output_json = json.dumps(all_discovered, indent=2)
        return output_json

    def generate(self, provider_name, model, messages,temperature=0.7, tools=None):
        config = self.CONFIGS.get(provider_name)
        if not config:
            return {"error": f"Error: Unknown provider '{provider_name}'"}
        
        api_key = os.getenv(config["api_key_env"])
        if not api_key:
            return {"error": f"Error: API key for {provider_name} ({config['api_key_env']}) is not set in environment."}

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        
        req_data = json.dumps(payload).encode("utf-8")
        headers = config["headers_fn"](api_key)
        req = urllib.request.Request(config["url"], data=req_data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                res_json = json.loads(response.read().decode("utf-8"))
                message = res_json["choices"][0]["message"]
                return res_json
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="ignore")
            return {"error": f"HTTP Error {e.code}: {error_body}"}
        except Exception as e:
            return {"error": f"Error: {str(e)}"}
