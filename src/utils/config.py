# -*- coding: utf-8 -*-
import os
import json
from dataclasses import dataclass, field
from typing import Set

class ConfigConstants:
    APP_NAME = "專業照片整理助手 (Pro)"
    VERSION = "2.2"
    CONFIG_FILE = "config.json"
    HISTORY_FILE = "history_log.json"
    BLOCK_SIZE = 65536
    
    EXT_PHOTOS: Set[str] = {'.jpg', '.jpeg', '.png', '.heic', '.bmp', '.tiff', '.raw', '.arw', '.webp'}
    EXT_VIDEOS: Set[str] = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.3gp', '.m4v'}
    EXT_JUNK: Set[str] = {'.json', '.ini', '.db', '.html', '.txt', '.tmp', '.url'}

class AppConfig:
    _instance = None

    def __init__(self):
        self.source_dir = ""
        self.dest_dir = ""
        self.skip_existing = False
        self.load()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def load(self):
        if os.path.exists(ConfigConstants.CONFIG_FILE):
            try:
                with open(ConfigConstants.CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.source_dir = data.get('source', '')
                    self.dest_dir = data.get('dest', '')
                    self.skip_existing = data.get('skip_existing', False)
            except Exception:
                pass

    def save(self):
        data = {
            'source': self.source_dir,
            'dest': self.dest_dir,
            'skip_existing': self.skip_existing
        }
        try:
            with open(ConfigConstants.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception:
            pass
