import json
import os
from typing import Optional


class LanguageManager:
    def __init__(self, lang_dir: str):
        self.lang_dir = lang_dir
        self.current_lang = 'km'
        self.strings = {}
        self._load('km')

    def _load(self, lang_code: str):
        filepath = os.path.join(self.lang_dir, lang_code + '.json')
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                self.strings = json.load(f)

    def switch_to(self, lang_code: str):
        self.current_lang = lang_code
        self._load(lang_code)

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self.strings.get(key, default)

    def get_available_languages(self):
        files = []
        for f in os.listdir(self.lang_dir):
            if f.endswith('.json'):
                code = f.replace('.json', '')
                name = self.get(f'english' if code == 'en' else 'khmer')
                files.append((code, name))
        return files
