"""
AI Analyzer module for Neuro-Connector Bot
Uses OpenRouter API to generate solutions and recommendations
"""

import aiohttp
import json
import logging
import base64
import asyncio
from pathlib import Path
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

class AIAnalyzer:
    """AI Analysis handler"""
    
    def __init__(self, openrouter_key: str, model: str = "gpt-4o", config=None):
        self.api_key = openrouter_key
        self.model = model
        self.base_url = "https://openrouter.ai/api/v1"
        self.config = config
        
        # Initialize local Whisper model for audio transcription
        # Using base model for faster processing, can be upgraded to medium/large if needed
        logger.info("Initializing local Whisper model for audio transcription...")
        self.whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
        logger.info("Whisper model loaded successfully")
    
    async def _call_api(self, prompt: str) -> str:
        """Call OpenRouter API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['choices'][0]['message']['content']
                    else:
                        error_text = await response.text()
                        logger.error(f"API error: {response.status} - {error_text}")
                        return "Извините, не удалось обработать ваш запрос. Попробуйте позже."
        except Exception as e:
            logger.error(f"API call failed: {e}")
            return "Извините, произошла ошибка при обработке запроса."
    
    async def generate_entrepreneur_solution(self, process_pain: str, time_lost: str, 
                                            department_affected: str) -> str:
        """Generate AI solution for entrepreneur"""
        
        company_name = self.config.company_name if self.config else "нашей компании"
        
        prompt = f"""
Ты — AI-бизнес-аналитик из IT-компании {company_name}. 
Твоя задача — проанализировать ответы предпринимателя и сгенерировать ОДНО, 
но очень конкретное и измеримое решение.

Проанализируй следующую проблему:
- Процесс-боль (что делают): "{process_pain}"
- Потери времени (сколько тратят): "{time_lost}"
- Страдающий отдел (кто страдает): "{department_affected}"

Сгенерируй конкретное решение. Решение должно быть направлено на автоматизацию 
описанного процесса. Оцени, сколько времени можно сэкономить.

Ответ должен быть в следующем формате (без кавычек):
> ✨ **РЕШЕНИЕ:**
[Краткое описание AI-решения, не более 60 слов. Текст должен быть практичным 
и показывать явную выгоду.]

💰 **РЕЗУЛЬТАТ:**
По нашей оценке, это может сэкономить [X-Y] часов в неделю и [дополнительная выгода].
"""
        
        response = await self._call_api(prompt)
        return response
    
    async def generate_startup_recommendations(self, problem_solved: str, current_stage: str, 
                                              main_barrier: str) -> str:
        """Generate MVP ideas and recommendations for startup"""
        
        company_name = self.config.company_name if self.config else "нашей компании"
        
        prompt = f"""
Ты — опытный AI-ментор для стартапов из компании {company_name}. 
Твоя задача — проанализировать идею основателя и дать ему два конкретных совета: 
один по MVP и один по типичной ошибке на его стадии.

Проанализируй идею стартапа:
- Проблема, которую решает идея: "{problem_solved}"
- Текущий этап: "{current_stage}"
- Главный барьер: "{main_barrier}"

Сгенерируй два совета в следующем формате (без кавычек):

> 💡 **ИДЕЯ ДЛЯ MVP:**
[Конкретная, выполнимая идея для MVP, не более 50 слов. Начинается с действия.]

> ⚠️ **ТИПИЧНАЯ ОШИБКА:**
[Описание одной типичной ошибки, которую стоит избегать на данном этапе, не более 50 слов.]
"""
        
        response = await self._call_api(prompt)
        return response
    
    async def generate_specialist_welcome(self, main_skill: str, project_interests: str, 
                                         work_format: str) -> str:
        """Generate personalized welcome message for specialist"""
        
        company_name = self.config.company_name if self.config else "нашей компании"
        
        prompt = f"""
Ты — дружелюбный AI-рекрутер из компании {company_name}. 
Твоя задача — проанализировать профиль специалиста и сгенерировать 
короткое, персонализированное сообщение, подтверждающее его добавление в базу талантов.

Профиль специалиста:
- Ключевой навык: "{main_skill}"
- Интересующие проекты: "{project_interests}"
- Формат работы: "{work_format}"

Сгенерируй персонализированное сообщение (не более 70 слов), 
которое упоминает ключевой навык и интересы специалиста, 
чтобы показать, что его профиль действительно прочитали.

Начни с: "Ваш опыт в..."
"""
        
        response = await self._call_api(prompt)
        return response
    
    async def transcribe_audio(self, audio_file_path: str) -> str:
        """
        Transcribe audio file using local Whisper model
        
        Args:
            audio_file_path: Path to audio file (mp3, mp4, ogg, wav, webm, etc.)
            
        Returns:
            Transcribed text
        """
        try:
            # Check if file exists
            audio_path = Path(audio_file_path)
            if not audio_path.exists():
                logger.error(f"Audio file not found: {audio_file_path}")
                return "Ошибка: файл не найден"
            
            logger.info(f"Transcribing audio file: {audio_file_path} (size: {audio_path.stat().st_size} bytes)")
            
            # Run Whisper transcription in a thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            segments, info = await loop.run_in_executor(
                None,
                lambda: self.whisper_model.transcribe(
                    audio_file_path,
                    language="ru",  # Force Russian language
                    beam_size=5,
                    vad_filter=True,  # Voice Activity Detection to filter out silence
                    vad_parameters=dict(min_silence_duration_ms=500)
                )
            )
            
            # Collect all transcribed text segments
            transcription_parts = []
            for segment in segments:
                transcription_parts.append(segment.text.strip())
            
            transcription = " ".join(transcription_parts).strip()
            
            if not transcription:
                logger.warning("Transcription resulted in empty text")
                return "Извините, не удалось распознать речь в аудио."
            
            logger.info(f"Audio transcribed successfully: '{transcription[:100]}...' ({len(transcription)} chars)")
            return transcription
            
        except Exception as e:
            logger.error(f"Audio transcription failed: {e}", exc_info=True)
            return "Извините, произошла ошибка при распознавании аудио."
    
    async def transcribe_audio_gemini(self, audio_file_path: str) -> str:
        """
        Transcribe audio using OpenRouter with Gemini model (multimodal).
        """
        try:
            audio_path = Path(audio_file_path)
            if not audio_path.exists():
                logger.error(f"Audio file not found: {audio_file_path}")
                return "Ошибка: файл не найден"

            file_size = audio_path.stat().st_size
            logger.info(f"Transcribing audio via Gemini: {audio_file_path} (size: {file_size} bytes)")

            with open(audio_file_path, 'rb') as f:
                audio_bytes = f.read()
            audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

            suffix = audio_path.suffix.lower().lstrip('.')
            mime_map = {
                'ogg': 'audio/ogg', 'oga': 'audio/ogg',
                'mp3': 'audio/mpeg', 'wav': 'audio/wav',
                'webm': 'audio/webm', 'm4a': 'audio/mp4',
            }
            mime_type = mime_map.get(suffix, 'audio/ogg')

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": "google/gemini-3-flash-preview",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": audio_b64,
                                    "format": suffix if suffix in ('wav', 'mp3') else 'ogg',
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Транскрибируй это аудиосообщение на русском языке. "
                                    "Верни ТОЛЬКО текст расшифровки, без комментариев, заголовков и пояснений. "
                                    "Сохрани структуру речи, пунктуацию и абзацы."
                                ),
                            },
                        ],
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 4000,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        transcription = data['choices'][0]['message']['content'].strip()
                        if not transcription:
                            return "Извините, не удалось распознать речь в аудио."
                        logger.info(f"Gemini transcription OK: '{transcription[:100]}...' ({len(transcription)} chars)")
                        return transcription
                    else:
                        error_text = await response.text()
                        logger.error(f"Gemini transcription API error {response.status}: {error_text}")
                        return "Извините, произошла ошибка при распознавании аудио."

        except Exception as e:
            logger.error(f"Gemini audio transcription failed: {e}", exc_info=True)
            return "Извините, произошла ошибка при распознавании аудио."

    async def analyze_business_card(self, image_url: str) -> dict:
        """Analyze business card image and extract contact information using Vision API"""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,  # gpt-4o supports vision
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": """Проанализируй эту визитку и извлеки все возможные контактные данные.

Верни ответ СТРОГО в формате JSON (без markdown, без ```json):
{
    "name": "Полное имя",
    "position": "Должность",
    "company": "Название компании",
    "phone": "Номер телефона",
    "email": "Email адрес",
    "website": "Веб-сайт",
    "address": "Адрес",
    "additional_info": "Любая дополнительная информация"
}

Если какое-то поле не найдено, укажи null. Извлекай ВСЕГДА все что видишь на визитке."""
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url
                            }
                        }
                    ]
                }
            ],
            "temperature": 0.1,  # Low temperature for precise extraction
            "max_tokens": 500
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        content = data['choices'][0]['message']['content']
                        
                        # Try to parse JSON from response
                        try:
                            # Remove markdown code blocks if present
                            if '```json' in content:
                                content = content.split('```json')[1].split('```')[0].strip()
                            elif '```' in content:
                                content = content.split('```')[1].split('```')[0].strip()
                            
                            card_data = json.loads(content)
                            logger.info(f"Business card analyzed successfully: {card_data}")
                            return card_data
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse JSON from AI response: {e}\nContent: {content}")
                            return {"error": "Не удалось распознать данные с визитки"}
                    else:
                        error_text = await response.text()
                        logger.error(f"Vision API error: {response.status} - {error_text}")
                        return {"error": "Ошибка при анализе изображения"}
        except Exception as e:
            logger.error(f"Business card analysis failed: {e}", exc_info=True)
            return {"error": "Произошла ошибка при анализе визитки"}
