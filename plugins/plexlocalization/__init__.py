import json
import re
import threading
from datetime import datetime, timedelta
from typing import Any, List, Dict, Tuple

import pytz
from app.core.config import settings
from app.log import logger
from app.modules.plex import Plex
from app.plugins import _PluginBase
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

lock = threading.Lock()


class PlexLocalization(_PluginBase):
    # 插件名称
    plugin_name = "Plex中文本地化"
    # 插件描述
    plugin_desc = "将Plex中的媒体信息进行中文本地化，从而支持拼音排序、拼音搜索及类型标签汉化功能。"
    # 插件图标
    plugin_icon = "Plex_A.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "InfinityPacer"
    # 作者主页
    author_url = "https://github.com/InfinityPacer"
    # 插件配置项ID前缀
    plugin_config_prefix = "plexlocalization_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1
    # Plex
    _plex = None

    # region 私有属性

    # 是否开启
    _enabled = False
    # 立即执行一次
    _onlyonce = False
    # 任务执行间隔
    _cron = None
    # 开启通知
    _notify = False
    # 需要处理的媒体库
    _library_ids = None
    # 锁定元数据
    _lock = None
    # tags_json
    _tags_json = None
    # tags
    _tags = None
    # 定时器
    _scheduler = None
    # 退出事件
    _event = threading.Event()

    # endregion

    def init_plugin(self, config: dict = None):
        self._plex = Plex()

        if not config:
            logger.info("Plex中文本地化开启失败，无法获取插件配置")
            return False

        self._enabled = config.get("enabled")
        self._onlyonce = config.get("onlyonce")
        self._cron = config.get("cron")
        self._notify = config.get("notify")
        self._library_ids = config.get("library_ids")
        self._lock = config.get("lock")
        self._tags_json = config.get("tags_json")
        self._tags = self.__get_tags()

        # 停止现有任务
        self.stop_service()

        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        if self._onlyonce:
            logger.info(f"Plex中文本地化服务，立即运行一次")
            self._scheduler.add_job(
                func=self.localization,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                name="Plex中文本地化",
            )
            # 关闭一次性开关
            self._onlyonce = False

        config_mapping = {
            "enabled": self._enabled,
            "onlyonce": False,
            "cron": self._cron,
            "notify": self._notify,
            "library_ids": self._library_ids,
            "lock": self._lock,
            "tags_json": self._tags_json,
        }
        self.update_config(config=config_mapping)

        # 启动任务
        if self._scheduler.get_jobs():
            self._scheduler.print_jobs()
            self._scheduler.start()

    def localization(self):
        pass

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        if not settings.MEDIASERVER:
            logger.info(f"媒体库配置不正确，请检查")

        if "plex" not in settings.MEDIASERVER:
            logger.info(f"Plex配置不正确，请检查")

        if not self._plex:
            self._plex = Plex()

        library = self._plex.get_plex().library
        # 获取所有媒体库
        libraries = library.sections()
        # 生成媒体库选项列表
        library_options = []

        # 遍历媒体库，创建字典并添加到列表中
        for library in libraries:
            library_dict = {
                "title": f"{library.key}. {library.title} ({library.TYPE})",
                "value": library.key
            }
            library_options.append(library_dict)

        library_options = sorted(library_options, key=lambda x: x["value"])

        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        },
                                    }
                                ],
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '开启通知',
                                        },
                                    }
                                ],
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期'
                                        },
                                    }
                                ],
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'lock',
                                            'label': '锁定元数据',
                                        },
                                    }
                                ],
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'dialog_closed',
                                            'label': '打开标签设置窗口',
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        'component': 'VRow',
                        'content': [

                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'library_ids',
                                            'multiple': True,
                                            'label': '媒体库',
                                            'items': library_options
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '注意：如开启锁定元数据，则本地化后需要在Plex中手动解锁才允许修改，'
                                                    '请先在测试媒体库验证无问题后再继续使用'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VDialog",
                        "props": {
                            "model": "dialog_closed",
                            "max-width": "60rem",
                            "overlay-class": "v-dialog--scrollable v-overlay--scroll-blocked",
                            "content-class": "v-card v-card--density-default v-card--variant-elevated rounded-t"
                        },
                        "content": [
                            {
                                "component": "VCard",
                                "props": {
                                    "title": "设置标签"
                                },
                                "content": [
                                    {
                                        "component": "VDialogCloseBtn",
                                        "props": {
                                            "model": "dialog_closed"
                                        }
                                    },
                                    {
                                        "component": "VCardText",
                                        "props": {},
                                        "content": [
                                            {
                                                'component': 'VRow',
                                                'content': [
                                                    {
                                                        'component': 'VCol',
                                                        'props': {
                                                            'cols': 12,
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'VAceEditor',
                                                                'props': {
                                                                    'modelvalue': 'tags_json',
                                                                    'lang': 'json',
                                                                    'theme': 'monokai',
                                                                    'style': 'height: 30rem',
                                                                }
                                                            }
                                                        ]
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VRow',
                                                'content': [
                                                    {
                                                        'component': 'VCol',
                                                        'props': {
                                                            'cols': 12,
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'VAlert',
                                                                'props': {
                                                                    'type': 'info',
                                                                    'variant': 'tonal',
                                                                    'text': '注意：已添加常用的中英标签，若需修改或新增可以在上述内容中添加'
                                                                }
                                                            }
                                                        ]
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ],
            }
        ], {
            "enabled": False,
            "notify": True,
            "cron": "0 */1 * * *",
            "lock": False,
            "tags_json": self.__get_preset_tags_json()
        }

    def get_page(self) -> List[dict]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        services = []

        if self._enabled and self._cron:
            logger.info(f"Plex中文本地化定时服务启动，时间间隔 {self._cron} ")
            services.append({
                "id": "PlexLocalization",
                "name": "Plex中文本地化",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.localization,
                "kwargs": {}
            })

        if not services:
            logger.info("Plex中文本地化服务定时服务未开启")

        return services

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            print(str(e))

    def __get_tags(self) -> str:
        try:
            # 如果预置Json被清空，这里还原为默认Json
            if not self._tags_json:
                self._tags_json = self.__get_preset_tags_json()

            # 去掉以//开始的行
            tags_json = re.sub(r'//.*?\n', '', self._tags_json).strip()
            tags = json.loads(tags_json)
            return tags
        except Exception as e:
            logger.error(f"解析标签失败，已停用插件，请检查配置项，错误详情: {e}")
            self._enabled = False

    @staticmethod
    def __get_preset_tags_json() -> str:
        """获取预置Json"""
        desc = ("// 以下为预置的常用标签的中英翻译\n"
                "// 若有其他标签需要汉化可以自己在下述内容中添加\n"
                "// 注意无关内容需使用 // 注释\n")
        config = """{
    "Anime": "动画",
    "Action": "动作",
    "Mystery": "悬疑",
    "Tv Movie": "电视电影",
    "Animation": "动画",
    "Crime": "犯罪",
    "Family": "家庭",
    "Fantasy": "奇幻",
    "Disaster": "灾难",
    "Adventure": "冒险",
    "Short": "短片",
    "Horror": "恐怖",
    "History": "历史",
    "Suspense": "悬疑",
    "Biography": "传记",
    "Sport": "运动",
    "Comedy": "喜剧",
    "Romance": "爱情",
    "Thriller": "惊悚",
    "Documentary": "纪录",
    "Indie": "独立",
    "Music": "音乐",
    "Sci-Fi": "科幻",
    "Western": "西部",
    "Children": "儿童",
    "Martial Arts": "武侠",
    "Drama": "剧情",
    "War": "战争",
    "Musical": "歌舞",
    "Film-noir": "黑色",
    "Science Fiction": "科幻",
    "Film-Noir": "黑色",
    "Food": "饮食",
    "War & Politics": "战争与政治",
    "Sci-Fi & Fantasy": "科幻与奇幻",
    "Mini-Series": "迷你剧",
    "Reality": "真人秀",
    "Home and Garden": "家居与园艺",
    "Game Show": "游戏节目",
    "Awards Show": "颁奖典礼",
    "News": "新闻",
    "Talk": "访谈",
    "Talk Show": "脱口秀",
    "Travel": "旅行",
    "Soap": "肥皂剧",
    "Rap": "说唱",
    "Adult": "成人"
}"""
        return desc + config
