import re
import threading
import time
import random
from datetime import datetime, timedelta
from threading import Event
from typing import Any, List, Dict, Tuple, Optional, Union, Set

import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from app import schemas
from app.chain.torrents import TorrentsChain
from app.core.config import settings
from app.db.site_oper import SiteOper
from app.db.subscribe_oper import SubscribeOper
from app.helper.sites import SitesHelper
from app.log import logger
from app.modules.qbittorrent import Qbittorrent
from app.modules.transmission import Transmission
from app.plugins import _PluginBase
from app.schemas import Notification, NotificationType, TorrentInfo
from app.utils.http import RequestUtils
from app.utils.string import StringUtils

lock = threading.Lock()

class BrushConfig:
    """
    刷流配置
    """
    def __init__(self, config: dict):
        self.enabled = config.get("enabled", False)
        self.notify = config.get("notify", True)
        self.onlyonce = config.get("onlyonce", False)
        self.brushsites = config.get("brushsites", [])
        self.downloader = config.get("downloader", "qbittorrent")
        self.disksize = self.__parse_number(config.get("disksize"))
        self.freeleech = config.get("freeleech", "free")
        self.hr = config.get("hr", "no")
        self.maxupspeed = self.__parse_number(config.get("maxupspeed"))
        self.maxdlspeed = self.__parse_number(config.get("maxdlspeed"))
        self.maxdlcount = self.__parse_number(config.get("maxdlcount"))
        self.include = config.get("include")
        self.exclude = config.get("exclude")
        self.size = config.get("size")
        self.seeder = config.get("seeder")
        self.pubtime = config.get("pubtime")
        self.seed_time = self.__parse_number(config.get("seed_time"))
        self.seed_ratio = self.__parse_number(config.get("seed_ratio"))
        self.seed_size = self.__parse_number(config.get("seed_size"))
        self.download_time = self.__parse_number(config.get("download_time"))
        self.seed_avgspeed = self.__parse_number(config.get("seed_avgspeed"))
        self.seed_inactivetime = self.__parse_number(config.get("seed_inactivetime"))
        self.up_speed = self.__parse_number(config.get("up_speed"))
        self.dl_speed = self.__parse_number(config.get("dl_speed"))
        self.save_path = config.get("save_path")
        self.clear_task = config.get("clear_task", False)
        self.archive_task = config.get("archive_task", False)
        self.except_tags = config.get("except_tags", True)
        self.except_subscribe = config.get("except_subscribe", True)
        self.brush_sequential = config.get("brush_sequential", False)
        self.proxy_download = config.get("proxy_download", False)

    @staticmethod
    def __parse_number(value):
        if value is None or value == '':  # 更精确地检查None或空字符串
            return value
        elif isinstance(value, int):  # 直接判断是否为int
            return value
        elif isinstance(value, float):  # 直接判断是否为float
            return value
        else:
            try:
                number = float(value)
                # 检查number是否等于其整数形式
                if number == int(number):
                    return int(number)
                else:
                    return number
            except (ValueError, TypeError):
                return 0
        
    def __str__(self):
        attrs = vars(self)
        attrs_str = ', '.join(f"{k}: {v}" for k, v in attrs.items())
        return f"{self.__class__.__name__}({attrs_str})"

class BrushFlowLowFreq(_PluginBase):
    
    # region 全局定义
    
    # 插件名称
    plugin_name = "站点刷流（低频版）"
    # 插件描述
    plugin_desc = "自动托管刷流，将会提高对应站点的访问频率。（基于官方插件BrushFlow二次开发）"
    # 插件图标
    plugin_icon = "brush.jpg"
    # 插件版本
    plugin_version = "1.6"
    # 插件作者
    plugin_author = "jxxghp,InfinityPacer"
    # 作者主页
    author_url = "https://github.com/InfinityPacer"
    # 插件配置项ID前缀
    plugin_config_prefix = "brushflowlowfreq_"
    # 加载顺序
    plugin_order = 21
    # 可使用的用户级别
    auth_level = 2

    # 私有属性
    siteshelper = None
    siteoper = None
    torrents = None
    sites = None
    qb = None
    tr = None
    # 刷流配置
    _brush_config = None
    # Brush任务是否启动
    _task_brush_enable = False
    # Brush定时
    _brush_interval = 10
    # Check定时
    _check_interval = 5
    # 退出事件
    _event = Event()
    _scheduler = None
    
    # endregion

    def init_plugin(self, config: dict = None): 
        logger.info(f"站点刷流服务初始化")
        self.siteshelper = SitesHelper()
        self.siteoper = SiteOper()
        self.torrents = TorrentsChain()
        self.sites = SitesHelper()
        self.subscribeoper = SubscribeOper()
        self._task_brush_enable = False
        
        if not config:
            logger.info("站点刷流任务出错，无法获取插件配置")
            return False
        
        # 如果配置校验没有通过，那么这里修改配置文件后退出
        if not self.__validate_and_fix_config(config=config):
            self._brush_config = BrushConfig(config=config)
            self._brush_config.enabled = False
            self.__update_config()
            return
        
        self._brush_config = BrushConfig(config=config)

        brush_config = self._brush_config
                        
        # 这里先过滤掉已删除的站点并保存，特别注意的是，这里保留了界面选择站点时的顺序，以便后续站点随机刷流或顺序刷流
        site_id_to_public_status = {site.get("id"): site.get("public") for site in self.sites.get_indexers()}
        brush_config.brushsites = [
            site_id for site_id in brush_config.brushsites
            if site_id in site_id_to_public_status and not site_id_to_public_status[site_id]
        ]

        self.__update_config()

        if brush_config.clear_task:
            self.save_data("statistic", {})
            self.save_data("torrents", {})
            self.save_data("archived_torrents", {})
            brush_config.clear_task = False
            self.__update_config()
            
        elif brush_config.archive_task:
            self.__archive_tasks()
            brush_config.archive_task = False
            self.__update_config()

        # 停止现有任务
        self.stop_service()
        
        if not self.__setup_downloader():
            return

        # 如果下载器都没有配置，那么这里也不需要继续
        if not brush_config.downloader:
            brush_config.enabled = False
            self.__update_config()
            logger.info(f"站点刷流服务停止，没有配置下载器")
            return

        # 如果站点都没有配置，则不开启定时刷流服务
        if not brush_config.brushsites:
            logger.info(f"站点刷流Brush定时服务停止，没有配置站点")

        # 如果开启&存在站点时，才需要启用后台任务
        self._task_brush_enable = brush_config.enabled and brush_config.brushsites
        
        # brush_config.onlyonce = True        
        
        # 检查是否启用了一次性任务
        if brush_config.onlyonce:
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            
            logger.info(f"站点刷流Brush服务启动，立即运行一次")
            self._scheduler.add_job(self.brush, 'date',
                                    run_date=datetime.now(
                                        tz=pytz.timezone(settings.TZ)
                                    ) + timedelta(seconds=3),
                                    name="站点刷流Brush服务")
            
            logger.info(f"站点刷流Check服务启动，立即运行一次")
            self._scheduler.add_job(self.check, 'date',
                                    run_date=datetime.now(
                                        tz=pytz.timezone(settings.TZ)
                                    ) + timedelta(seconds=3),
                                    name="站点刷流Check服务")
            
            # 关闭一次性开关
            brush_config.onlyonce = False
            self.__update_config()

            # 存在任务则启动任务
            if self._scheduler.get_jobs():
                # 启动服务
                self._scheduler.print_jobs()
                self._scheduler.start()
                
    def get_state(self) -> bool:
        brush_config = self.__get_brush_config()
        return True if brush_config.enabled else False

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
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
        
        brush_config = self.__get_brush_config()
        
        if self._task_brush_enable:
            logger.info(f"站点刷流Brush定时服务启动，时间间隔 {self._brush_interval} 分钟")
            services.append({
                "id": "BrushFlowLowFreq",
                "name": "站点刷流（低频版）Brush服务",
                "trigger": "interval",
                "func": self.brush,
                "kwargs": {"minutes": self._brush_interval}
            })
            
        if brush_config.enabled:
            logger.info(f"站点刷流Check定时服务启动，时间间隔 {self._check_interval} 分钟")
            services.append({
                "id": "BrushFlowLowFreqCheck",
                "name": "站点刷流（低频版）Check服务",
                "trigger": "interval",
                "func": self.check,
                "kwargs": {"minutes": self._check_interval}
            })

        if not services:
            logger.info("站点刷流服务未开启")

        return services

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        # 站点的可选项
        site_options = [{"title": site.get("name"), "value": site.get("id")}
                        for site in self.siteshelper.get_indexers()]
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
                                        }
                                    }
                                ]
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
                                            'label': '发送通知',
                                        }
                                    }
                                ]
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
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'chips': True,
                                            'multiple': True,
                                            'model': 'brushsites',
                                            'label': '刷流站点',
                                            'items': site_options
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
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'downloader',
                                            'label': '下载器',
                                            'items': [
                                                {'title': 'Qbittorrent', 'value': 'qbittorrent'},
                                                {'title': 'Transmission', 'value': 'transmission'}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'disksize',
                                            'label': '保种体积（GB）',
                                            'placeholder': '达到后停止新增任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'freeleech',
                                            'label': '促销',
                                            'items': [
                                                {'title': '全部（包括普通）', 'value': ''},
                                                {'title': '免费', 'value': 'free'},
                                                {'title': '2X免费', 'value': '2xfree'},
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'hr',
                                            'label': '排除H&R',
                                            'items': [
                                                {'title': '是', 'value': 'yes'},
                                                {'title': '否', 'value': 'no'},
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'maxupspeed',
                                            'label': '总上传带宽（KB/s）',
                                            'placeholder': '达到后停止新增任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'maxdlspeed',
                                            'label': '总下载带宽（KB/s）',
                                            'placeholder': '达到后停止新增任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'maxdlcount',
                                            'label': '同时下载任务数',
                                            'placeholder': '达到后停止新增任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'include',
                                            'label': '包含规则',
                                            'placeholder': '支持正式表达式'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'exclude',
                                            'label': '排除规则',
                                            'placeholder': '支持正式表达式'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'size',
                                            'label': '种子大小（GB）',
                                            'placeholder': '如：5 或 5-10'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'seeder',
                                            'label': '做种人数',
                                            'placeholder': '如：5 或 5-10'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'pubtime',
                                            'label': '发布时间（分钟）',
                                            'placeholder': '如：5 或 5-10'
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
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'seed_time',
                                            'label': '做种时间（小时）',
                                            'placeholder': '达到后删除任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'seed_ratio',
                                            'label': '分享率',
                                            'placeholder': '达到后删除任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'seed_size',
                                            'label': '上传量（GB）',
                                            'placeholder': '达到后删除任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'download_time',
                                            'label': '下载超时时间（小时）',
                                            'placeholder': '达到后删除任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'seed_avgspeed',
                                            'label': '平均上传速度（KB/s）',
                                            'placeholder': '低于时删除任务'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'seed_inactivetime',
                                            'label': '未活动时间（分钟） ',
                                            'placeholder': '超过时删除任务'
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
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'up_speed',
                                            'label': '单任务上传限速（KB/s）',
                                            'placeholder': '种子上传限速'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'dl_speed',
                                            'label': '单任务下载限速（KB/s）',
                                            'placeholder': '种子下载限速'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    "cols": 12,
                                    "md": 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'save_path',
                                            'label': '保存目录',
                                            'placeholder': '留空自动'
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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'brush_sequential',
                                            'label': '站点顺序刷流',
                                        }
                                    }
                                ]
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
                                            'model': 'except_tags',
                                            'label': '删种排除MoviePilot任务',
                                        }
                                    }
                                ]
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
                                            'model': 'except_subscribe',
                                            'label': '排除订阅（实验性功能）',
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
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'clear_task',
                                            'label': '清除统计数据',
                                        }
                                    }
                                ]
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
                                            'model': 'archive_task',
                                            'label': '归档已删除种子',
                                        }
                                    }
                                ]
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
                                            'model': 'proxy_download',
                                            'label': '代理下载种子',
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
                                            'text': '注意：排除H&R并不保证能完全适配所有站点（部分站点在列表页不显示H&R标志，但实际上是有H&R的），请注意核对使用！'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "notify": True,
            "onlyonce": False,
            "clear_task": False,
            "archive_task": False,
            "except_tags": True,
            "except_subscribe": True,
            "brush_sequential": False,
            "proxy_download": False,
            "freeleech": "free",
            "hr": "yes",
        }

    def get_page(self) -> List[dict]:
        # 种子明细
        torrents = self.get_data("torrents") or {}
        # 统计数据
        stattistic_data: Dict[str, dict] = self.get_data("statistic") or {
            "count": 0,
            "deleted": 0,
            "uploaded": 0,
            "downloaded": 0,
        }
        if not torrents:
            return [
                {
                    'component': 'div',
                    'text': '暂无数据',
                    'props': {
                        'class': 'text-center',
                    }
                }
            ]
        else:
            data_list = torrents.values()
            # 按time倒序排序
            data_list = sorted(data_list, key=lambda x: x.get("time") or 0, reverse=True)
        # 总上传量格式化
        total_upload = StringUtils.str_filesize(stattistic_data.get("uploaded") or 0)
        # 总下载量格式化
        total_download = StringUtils.str_filesize(stattistic_data.get("downloaded") or 0)
        # 下载种子数
        total_count = stattistic_data.get("count") or 0
        # 删除种子数
        total_deleted = stattistic_data.get("deleted") or 0
        # 活跃种子数
        total_active = stattistic_data.get("active") or 0
        # 种子数据明细
        torrent_trs = [
            {
                'component': 'tr',
                'props': {
                    'class': 'text-sm'
                },
                'content': [
                    {
                        'component': 'td',
                        'props': {
                            'class': 'whitespace-nowrap break-keep text-high-emphasis'
                        },
                        'text': data.get("site_name")
                    },
                    {
                        'component': 'td',
                        'props': {
                            'style': 'font-size: .75rem; line-height: 1.15rem;'
                        },
                        'html': data.get("title") + ("<br>" + data.get("description") if data.get("description") else "")
                    },
                    {
                        'component': 'td',
                        'text': StringUtils.str_filesize(data.get("size"))
                    },
                    {
                        'component': 'td',
                        'text': StringUtils.str_filesize(data.get("uploaded") or 0)
                    },
                    {
                        'component': 'td',
                        'text': StringUtils.str_filesize(data.get("downloaded") or 0)
                    },
                    {
                        'component': 'td',
                        'text': round(data.get('ratio') or 0, 2)
                    },
                    {
                        'component': 'td',
                        'props': {
                            'class': 'text-no-wrap'
                        },
                        'text': "已删除" if data.get("deleted") else "正常"
                    }
                ]
            } for data in data_list
        ]
             
        # 拼装页面
        return [
            {
                'component': 'VRow',
                'content': [
                    # 总上传量
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 3,
                            'sm': 6
                        },
                        'content': [
                            {
                                'component': 'VCard',
                                'props': {
                                    'variant': 'tonal',
                                },
                                'content': [
                                    {
                                        'component': 'VCardText',
                                        'props': {
                                            'class': 'd-flex align-center',
                                        },
                                        'content': [
                                            {
                                                'component': 'VAvatar',
                                                'props': {
                                                    'rounded': True,
                                                    'variant': 'text',
                                                    'class': 'me-3'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VImg',
                                                        'props': {
                                                            'src': '/plugin_icon/upload.png'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'div',
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'props': {
                                                            'class': 'text-caption'
                                                        },
                                                        'text': '总上传量'
                                                    },
                                                    {
                                                        'component': 'div',
                                                        'props': {
                                                            'class': 'd-flex align-center flex-wrap'
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'span',
                                                                'props': {
                                                                    'class': 'text-h6'
                                                                },
                                                                'text': total_upload
                                                            }
                                                        ]
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                        ]
                    },
                    # 总下载量
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 3,
                            'sm': 6
                        },
                        'content': [
                            {
                                'component': 'VCard',
                                'props': {
                                    'variant': 'tonal',
                                },
                                'content': [
                                    {
                                        'component': 'VCardText',
                                        'props': {
                                            'class': 'd-flex align-center',
                                        },
                                        'content': [
                                            {
                                                'component': 'VAvatar',
                                                'props': {
                                                    'rounded': True,
                                                    'variant': 'text',
                                                    'class': 'me-3'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VImg',
                                                        'props': {
                                                            'src': '/plugin_icon/download.png'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'div',
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'props': {
                                                            'class': 'text-caption'
                                                        },
                                                        'text': '总下载量'
                                                    },
                                                    {
                                                        'component': 'div',
                                                        'props': {
                                                            'class': 'd-flex align-center flex-wrap'
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'span',
                                                                'props': {
                                                                    'class': 'text-h6'
                                                                },
                                                                'text': total_download
                                                            }
                                                        ]
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                        ]
                    },
                    # 下载种子数
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 2,
                            'sm': 6
                        },
                        'content': [
                            {
                                'component': 'VCard',
                                'props': {
                                    'variant': 'tonal',
                                },
                                'content': [
                                    {
                                        'component': 'VCardText',
                                        'props': {
                                            'class': 'd-flex align-center',
                                        },
                                        'content': [
                                            {
                                                'component': 'VAvatar',
                                                'props': {
                                                    'rounded': True,
                                                    'variant': 'text',
                                                    'class': 'me-3'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VImg',
                                                        'props': {
                                                            'src': '/plugin_icon/seed.png'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'div',
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'props': {
                                                            'class': 'text-caption'
                                                        },
                                                        'text': '下载种子数'
                                                    },
                                                    {
                                                        'component': 'div',
                                                        'props': {
                                                            'class': 'd-flex align-center flex-wrap'
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'span',
                                                                'props': {
                                                                    'class': 'text-h6'
                                                                },
                                                                'text': total_count
                                                            }
                                                        ]
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
                        ]
                    },
                    # 删除种子数
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 2,
                            'sm': 6
                        },
                        'content': [
                            {
                                'component': 'VCard',
                                'props': {
                                    'variant': 'tonal',
                                },
                                'content': [
                                    {
                                        'component': 'VCardText',
                                        'props': {
                                            'class': 'd-flex align-center',
                                        },
                                        'content': [
                                            {
                                                'component': 'VAvatar',
                                                'props': {
                                                    'rounded': True,
                                                    'variant': 'text',
                                                    'class': 'me-3'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VImg',
                                                        'props': {
                                                            'src': '/plugin_icon/delete.png'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'div',
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'props': {
                                                            'class': 'text-caption'
                                                        },
                                                        'text': '删除种子数'
                                                    },
                                                    {
                                                        'component': 'div',
                                                        'props': {
                                                            'class': 'd-flex align-center flex-wrap'
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'span',
                                                                'props': {
                                                                    'class': 'text-h6'
                                                                },
                                                                'text': total_deleted
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
                    },
                    # 活跃种子数
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                            'md': 2,
                            'sm': 6
                        },
                        'content': [
                            {
                                'component': 'VCard',
                                'props': {
                                    'variant': 'tonal',
                                },
                                'content': [
                                    {
                                        'component': 'VCardText',
                                        'props': {
                                            'class': 'd-flex align-center',
                                        },
                                        'content': [
                                            {
                                                'component': 'VAvatar',
                                                'props': {
                                                    'rounded': True,
                                                    'variant': 'text',
                                                    'class': 'me-3'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VImg',
                                                        'props': {
                                                            'src': '/plugin_icon/spider.png'
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'div',
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'props': {
                                                            'class': 'text-caption'
                                                        },
                                                        'text': '活跃种子数'
                                                    },
                                                    {
                                                        'component': 'div',
                                                        'props': {
                                                            'class': 'd-flex align-center flex-wrap'
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'span',
                                                                'props': {
                                                                    'class': 'text-h6'
                                                                },
                                                                'text': total_active
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
                    },
                    # 种子明细
                    {
                        'component': 'VCol',
                        'props': {
                            'cols': 12,
                        },
                        'content': [
                            {
                                'component': 'VTable',
                                'props': {
                                    'hover': True
                                },
                                'content': [
                                    {
                                        'component': 'thead',
                                        'props': {
                                            'class': 'text-no-wrap'
                                        },
                                        'content': [
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '站点'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '标题'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '大小'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '上传量'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '下载量'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '分享率'
                                            },
                                            {
                                                'component': 'th',
                                                'props': {
                                                    'class': 'text-start ps-4'
                                                },
                                                'text': '状态'
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'tbody',
                                        'content': torrent_trs
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

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

    #region Brush

    def brush(self):
        """
        定时刷流，添加下载任务
        """
        brush_config = self.__get_brush_config()
        
        if not brush_config.brushsites or not brush_config.downloader:
            return

        with lock:
            logger.info(f"开始执行刷流任务 ...")
          
            torrent_tasks: Dict[str, dict] = self.get_data("torrents") or {}
            torrents_size = self.__calculate_seeding_torrents_size(torrent_tasks=torrent_tasks)
            
            # 判断能否通过刷流前置条件
            pre_condition_passed, reason = self.__evaluate_pre_conditions_for_brush(torrents_size=torrents_size)
            if not pre_condition_passed:
                return
                
            statistic_info = self.get_data("statistic") or {"count": 0, "deleted": 0, "uploaded": 0, "downloaded": 0}

            # 获取所有站点的信息，并过滤掉不存在的站点
            site_infos = []
            for siteid in brush_config.brushsites:
                siteinfo = self.siteoper.get(siteid)
                if siteinfo:
                    site_infos.append(siteinfo)

            # 根据是否开启顺序刷流来决定是否需要打乱顺序
            if not brush_config.brush_sequential:
                random.shuffle(site_infos)

            logger.info(f"即将针对站点 {', '.join(site.name for site in site_infos)} 开始刷流")
            
            # 处理所有站点
            for site in site_infos:
                # 如果站点刷流没有正确响应，说明没有通过前置条件，其他站点也不需要继续刷流了
                if not self.__brush_site_torrents(siteid=site.id, torrent_tasks=torrent_tasks, statistic_info=statistic_info):
                    logger.info(f"站点 {site.name} 刷流中途结束，停止后续站点刷流")
                    break
                else:
                    logger.info(f"站点 {site.name} 刷流完成，继续处理后续站点")
                
            # 保存数据
            self.save_data("torrents", torrent_tasks)
            # 保存统计数据
            self.save_data("statistic", statistic_info)
            logger.info(f"刷流任务执行完成")
            
    def __brush_site_torrents(self, siteid, torrent_tasks, statistic_info) -> bool:
        brush_config = self.__get_brush_config()
        
        siteinfo = self.siteoper.get(siteid)
        if not siteinfo:
            logger.warn(f"站点不存在：{siteid}")
            return True
        
        logger.info(f"开始获取站点 {siteinfo.name} 的新种子 ...")
        torrents = self.torrents.browse(domain=siteinfo.domain)
        if not torrents:
            logger.info(f"站点 {siteinfo.name} 没有获取到种子")
            return True
        
        # 排除包含订阅的种子
        if brush_config.except_subscribe:
            torrents = self.__filter_torrents_contains_subscribe(torrents=torrents)
        
        # 按发布日期降序排列
        torrents.sort(key=lambda x: x.pubdate or '', reverse=True)
        
        torrents_size = self.__calculate_seeding_torrents_size(torrent_tasks=torrent_tasks)
         
        logger.info(f"正在准备种子刷流，数量：{len(torrents)}")
        
        # 过滤种子
        for torrent in torrents:
            # 判断能否通过刷流前置条件
            seeding_size = torrents_size + torrent.size
            pre_condition_passed, reason = self.__evaluate_pre_conditions_for_brush(torrents_size=seeding_size, include_network_conditions=False) 
            if not pre_condition_passed:
                # logger.info(f"种子没有通过刷流前置条件校验，原因：{reason} 种子：{torrent.title}|{torrent.description}")
                return False
            # else:
            #     logger.info(f"种子已通过刷流前置校验，种子：{torrent.title}|{torrent.description}")
                
            # 判断能否通过刷流条件
            condition_passed, reason = self.__evaluate_conditions_for_brush(torrent=torrent, torrent_tasks=torrent_tasks)
            if not condition_passed:
                # logger.info(f"种子没有通过刷流条件校验，原因：{reason} 种子：{torrent.title}|{torrent.description}")
                continue
            # else:
            #     logger.info(f"种子已通过刷流条件校验，种子：{torrent.title}|{torrent.description}")

            # 添加下载任务
            hash_string = self.__download(torrent=torrent)
            if not hash_string:
                logger.warn(f"{torrent.title} 添加刷流任务失败！")
                continue
            
            # 保存任务信息
            torrent_tasks[hash_string] = {
                "site": siteinfo.id,
                "site_name": siteinfo.name,
                "title": torrent.title,
                "size": torrent.size,
                "pubdate": torrent.pubdate,
                # "site_cookie": torrent.site_cookie,
                # "site_ua": torrent.site_ua,
                # "site_proxy": torrent.site_proxy,
                # "site_order": torrent.site_order,
                "description": torrent.description,
                "imdbid": torrent.imdbid,
                # "enclosure": torrent.enclosure,
                "page_url": torrent.page_url,
                # "seeders": torrent.seeders,
                # "peers": torrent.peers,
                # "grabs": torrent.grabs,
                "date_elapsed": torrent.date_elapsed,
                "freedate": torrent.freedate,
                "uploadvolumefactor": torrent.uploadvolumefactor,
                "downloadvolumefactor": torrent.downloadvolumefactor,
                "hit_and_run": torrent.hit_and_run,
                "volume_factor": torrent.volume_factor,
                "freedate_diff": torrent.freedate_diff,
                # "labels": torrent.labels,
                # "pri_order": torrent.pri_order,
                # "category": torrent.category,
                "ratio": 0,
                "downloaded": 0,
                "uploaded": 0,
                "deleted": False,
                "time": time.time()
            }
                        
            # 统计数据
            torrents_size += torrent.size
            statistic_info["count"] += 1
            logger.info(f"站点 {siteinfo.name} 刷流种子下载：{torrent.title}|{torrent.description}")
            self.__send_add_message(torrent)
            
        return True

    def __evaluate_pre_conditions_for_brush(self, torrents_size: int, include_network_conditions: bool = True) -> Tuple[bool, str]:
        reasons = [
            ("maxdlcount", lambda config: self.__get_downloading_count() >= int(config),
             lambda config: f"当前同时下载任务数已达到最大值 {config}，暂时停止新增任务"),
            ("disksize", lambda config: torrents_size > float(config) * 1024 ** 3,
             lambda config: f"当前做种体积 {self.__bytes_to_gb(torrents_size):.2f} GB，已超过保种体积 {config} GB，暂时停止新增任务"),
        ]
        
        if include_network_conditions:
            downloader_info = self.__get_downloader_info()
            if downloader_info:
                current_upload_speed = downloader_info.upload_speed or 0
                current_download_speed = downloader_info.download_speed or 0
                reasons.extend([
                    ("maxupspeed", lambda config: current_upload_speed >= float(config) * 1024,
                    lambda config: f"当前总上传带宽 {StringUtils.str_filesize(current_upload_speed)}，已达到最大值 {config} KB/s，暂时停止新增任务"),
                    ("maxdlspeed", lambda config: current_download_speed >= float(config) * 1024,
                    lambda config: f"当前总下载带宽 {StringUtils.str_filesize(current_download_speed)}，已达到最大值 {config} KB/s，暂时停止新增任务"),
                ])
            
        brush_config = self.__get_brush_config()
        for condition, check, message in reasons:
            config_value = getattr(brush_config, condition, None)
            if config_value and check(config_value):
                reason = message(config_value)
                logger.warn(reason)
                return False, reason

        return True, None

    def __evaluate_conditions_for_brush(self, torrent, torrent_tasks) -> Tuple[bool, str]:
        """
        过滤不符合条件的种子
        """
        brush_config = self.__get_brush_config()
                
        task_key = f"{torrent.site_name}{torrent.title}"
        if any(task_key == f"{task.get('site_name')}{task.get('title')}" for task in torrent_tasks.values()):
            return False, "重复种子"

        # 促销条件
        if brush_config.freeleech and torrent.downloadvolumefactor != 0:
            return False, "非免费种子"
        if brush_config.freeleech == "2xfree" and torrent.uploadvolumefactor != 2:
            return False, "非双倍上传种子"

        # H&R
        if brush_config.hr == "yes" and torrent.hit_and_run:
            return False, "存在H&R"

        # 包含规则
        if brush_config.include and not (re.search(brush_config.include, torrent.title, re.I) or re.search(brush_config.include, torrent.description, re.I)):
            return False, "不符合包含规则"
        
        # 排除规则
        if brush_config.exclude and (re.search(brush_config.exclude, torrent.title, re.I) or re.search(brush_config.exclude, torrent.description, re.I)):
            return False, "符合排除规则"
        
        # 种子大小（GB）
        if brush_config.size:
            sizes = [float(size) * 1024**3 for size in brush_config.size.split("-")]
            if len(sizes) == 1 and torrent.size < sizes[0]:
                return False, "种子大小不符合条件"
            elif len(sizes) > 1 and not sizes[0] <= torrent.size <= sizes[1]:
                return False, "种子大小不在指定范围内"
            
        # 做种人数
        if brush_config.seeder:
            seeders_range = [int(n) for n in brush_config.seeder.split("-")]
            # 检查是否仅指定了一个数字，即做种人数需要小于等于该数字
            if len(seeders_range) == 1:
                # 当做种人数大于该数字时，不符合条件
                if torrent.seeders > seeders_range[0]:
                    return False, "做种人数超过单个指定值"
            # 如果指定了一个范围
            elif len(seeders_range) > 1:
                # 检查做种人数是否在指定的范围内（包括边界）
                if not (seeders_range[0] <= torrent.seeders <= seeders_range[1]):
                    return False, "做种人数不在指定范围内"

        # 发布时间
        pubdate_minutes = self.__get_pubminutes(torrent.pubdate)
        pubdate_minutes = self.__adjust_site_pubminutes(pubdate_minutes, torrent)
        if brush_config.pubtime:
            pubtimes = [int(n) for n in brush_config.pubtime.split("-")]
            if len(pubtimes) == 1:
                # 单个值：选择发布时间小于等于该值的种子
                if pubdate_minutes > pubtimes[0]:
                    return False, "发布时间不符合条件"
            else:
                # 范围值：选择发布时间在范围内的种子
                if not (pubtimes[0] <= pubdate_minutes <= pubtimes[1]):
                    return False, "发布时间不在指定范围内"

        return True, None

    #endregion
  
    #region Check
    
    def check(self):
        """
        定时检查，删除下载任务
        """
        brush_config = self.__get_brush_config()

        if not brush_config.downloader:
            return

        with lock:
            logger.info("开始检查刷流下载任务 ...")
            torrent_tasks: Dict[str, dict] = self.get_data("torrents") or {}
            torrent_check_hashes = list(torrent_tasks.keys())

            if not torrent_tasks or not torrent_check_hashes:
                logger.info("没有需要检查的刷流下载任务")
                return

            logger.info(f"共有 {len(torrent_check_hashes)} 个任务正在刷流，开始检查任务状态")

            downloader = self.__get_downloader(brush_config.downloader)
            if not downloader:
                logger.warn("无法获取下载器实例，将在下个时间周期重试")
                return

            torrents, error = downloader.get_torrents(ids=torrent_check_hashes)
            if error:
                logger.warn("连接下载器出错，将在下个时间周期重试")
                return
            
            # 排除MoviePilot种子
            if torrents and brush_config.except_tags:
                torrents = self.__filter_torrents_by_tag(torrents=torrents, exclude_tag=settings.TORRENT_TAG)

            # 统计删除状态
            remove_hashes = self.__delete_torrent_and_get_removes(torrents=torrents, torrent_tasks=torrent_tasks) or []
                 
            not_deleted_hashes = self.__handle_not_deleted_hashes(torrent_tasks, torrent_check_hashes, torrents) or []
            
            all_deleted_hashes = remove_hashes + not_deleted_hashes

            if all_deleted_hashes:
                for hash in all_deleted_hashes:
                    torrent_tasks[hash]["deleted"] = True
            
            self.__update_and_save_statistic_info(torrent_tasks)
            
            logger.info("刷流下载任务检查完成")
  
    def __evaluate_conditions_and_delete(self, torrent_info) -> Tuple[bool, str]:
        """
        评估删除条件并返回是否应删除种子及其原因
        """
        
        brush_config = self.__get_brush_config()
        
        if brush_config.seed_time and torrent_info.get("seeding_time") >= float(brush_config.seed_time) * 3600:
            reason = f"做种时间达到 {brush_config.seed_time} 小时"
        elif brush_config.seed_ratio and torrent_info.get("ratio") >= float(brush_config.seed_ratio):
            reason = f"分享率达到 {brush_config.seed_ratio}"
        elif brush_config.seed_size and torrent_info.get("uploaded") >= float(brush_config.seed_size) * 1024**3:
            reason = f"上传量达到 {brush_config.seed_size} GB"
        elif brush_config.download_time and torrent_info.get("downloaded") < torrent_info.get("total_size") and torrent_info.get("dltime") >= float(brush_config.download_time) * 3600:
            reason = f"下载耗时达到 {brush_config.download_time} 小时"
        elif brush_config.seed_avgspeed and torrent_info.get("avg_upspeed") <= float(brush_config.seed_avgspeed) * 1024 and torrent_info.get("seeding_time") >= 30 * 60:
            reason = f"平均上传速度低于 {brush_config.seed_avgspeed} KB/s"
        elif brush_config.seed_inactivetime and torrent_info.get("iatime") >= float(brush_config.seed_inactivetime) * 60:
            reason = f"未活动时间达到 {brush_config.seed_inactivetime} 分钟"
        else:
            return False, ""

        return True, reason
            
    def __delete_torrent_and_get_removes(self, torrents: List[Any], torrent_tasks: Dict[str, dict]) -> List:
        """
        根据条件删除种子并获取已删除列表
        """     
        remove_hashes = []
        
        brush_config = self.__get_brush_config()
        downloader = self.__get_downloader(brush_config.downloader)
        
        for torrent in torrents:
            torrent_hash = self.__get_hash(torrent)
            site_name = torrent_tasks.get(torrent_hash, {}).get("site_name", "")
            torrent_info = self.__get_torrent_info(torrent)
            
            # 更新上传量、下载量
            torrent_tasks.setdefault(torrent_hash, {}).update({
                "downloaded": torrent_info.get("downloaded"),
                "uploaded": torrent_info.get("uploaded"),
                "ratio": torrent_info.get("ratio"),
            })

            should_delete, reason = self.__evaluate_conditions_and_delete(torrent_info)
            if should_delete:
                # 删除种子的具体实现可能会根据实际情况略有不同
                downloader.delete_torrents(ids=torrent_hash, delete_file=True)
                remove_hashes.append(torrent_info.get("hash"))
                torrent_title = torrent_info.get("title")
                self.__send_delete_message(site_name=site_name, torrent_title=torrent_title, reason=reason)
                logger.info(f"{reason}，删除种子：{torrent_title}")

        return remove_hashes
    
    def __handle_not_deleted_hashes(self, torrent_tasks, torrent_check_hashes, torrents) -> List:
        """
        处理已经被删除，但是任务记录中还没有被标记删除的种子
        """
        torrent_all_hashes = self.__get_all_hashes(torrents)
        missing_hashes = [hash_value for hash_value in torrent_check_hashes if hash_value not in torrent_all_hashes]
        not_deleted_hashes = [hash_value for hash_value in missing_hashes if not torrent_tasks[hash_value].get("deleted")]

        if not not_deleted_hashes:
            return []
                
        # 处理每个符合条件的任务
        for hash_value in not_deleted_hashes:
            # 获取对应的任务信息
            torrent_info = torrent_tasks[hash_value]
            # 获取site_name和torrent_title
            site_name = torrent_info["site_name"]
            torrent_title = torrent_info["title"]
            logger.info(f"下载器中找不到种子，可能已经被删除，种子信息:{torrent_info}")
            # 发送删除消息
            self.__send_delete_message(site_name=site_name,
                                        torrent_title=torrent_title,
                                        reason="下载器中找不到种子")
        
        return not_deleted_hashes

    def __update_and_save_statistic_info(self, torrent_tasks):
        total_count, total_uploaded, total_downloaded, total_deleted = 0, 0, 0, 0
        
        statistic_info = self.get_data("statistic") or {"count": 0, "deleted": 0, "uploaded": 0, "downloaded": 0}
        archived_tasks = self.get_data("archived_torrents") or {}
        combined_tasks = {**torrent_tasks, **archived_tasks}

        for task in combined_tasks.values():
            if task.get("deleted", False):
                total_deleted += 1
            total_downloaded += task.get("downloaded", 0)
            total_uploaded += task.get("uploaded", 0)

        # 更新统计信息
        total_count = len(combined_tasks)
        active_tasks_count = total_count - total_deleted
        statistic_info.update({
            "uploaded": total_uploaded,
            "downloaded": total_downloaded,
            "deleted": total_deleted,
            "count": total_count,
            "active": active_tasks_count
        })

        logger.info(f"刷流任务统计数据：总任务数：{total_count}，活跃任务数：{active_tasks_count}，已删除：{total_deleted}，"
                f"总上传量：{StringUtils.str_filesize(total_uploaded)}，"
                f"总下载量：{StringUtils.str_filesize(total_downloaded)}")

        self.save_data("statistic", statistic_info)
        self.save_data("torrents", torrent_tasks)

    #endregion

    def __get_brush_config(self) -> BrushConfig:
        """
        获取BrushConfig
        """
        return self._brush_config

    def __validate_and_fix_config(self, config: dict = None) -> bool:
        """
        检查并修正配置值
        """    
        if config is None:
            logger.error("配置为None，无法验证和修正")
            return False

        # 设置一个标志，用于跟踪是否发现校验错误
        found_error = False

        config_number_attr_to_desc = {
            "disksize": "保种体积",
            "maxupspeed": "总上传带宽",
            "maxdlspeed": "总下载带宽",
            "maxdlcount": "同时下载任务数",
            "seed_time": "做种时间",
            "seed_ratio": "分享率",
            "seed_size": "上传量",
            "download_time": "下载超时时间",
            "seed_avgspeed": "平均上传速度",
            "seed_inactivetime": "未活动时间",
            "up_speed": "单任务上传限速",
            "dl_speed": "单任务下载限速"
        }
        
        config_range_number_attr_to_desc = {
            "pubtime": "发布时间",
            "size": "种子大小",
            "seeder": "做种人数"
        }
                
        for attr, desc in config_number_attr_to_desc.items():
            value = config.get(attr)
            if value and not self.__is_number(value):
                self.__log_and_notify_error(f"站点刷流任务出错，{desc}设置错误：{value}")
                config[attr] = 0
                found_error = True  # 更新错误标志

        for attr, desc in config_range_number_attr_to_desc.items():
            value = config.get(attr)
            # 检查 value 是否存在且是否符合数字或数字-数字的模式
            if value and not self.__is_number_or_range(str(value)):
                self.__log_and_notify_error(f"站点刷流任务出错，{desc}设置错误：{value}")
                config[attr] = 0
                found_error = True  # 更新错误标志
            
        # 如果发现任何错误，返回False；否则返回True
        return not found_error

    def __update_config(self, brush_config: BrushConfig = None):
        """
        根据传入的BrushConfig实例更新配置
        """
        if brush_config is None:
            brush_config = self._brush_config
            
        if brush_config is None:
            return
        
        # 创建一个将配置属性名称映射到BrushConfig属性值的字典
        config_mapping = {
            "onlyonce": brush_config.onlyonce,
            "enabled": brush_config.enabled,
            "notify": brush_config.notify,
            "brushsites": brush_config.brushsites,
            "downloader": brush_config.downloader,
            "disksize": brush_config.disksize,
            "freeleech": brush_config.freeleech,
            "hr": brush_config.hr,
            "maxupspeed": brush_config.maxupspeed,
            "maxdlspeed": brush_config.maxdlspeed,
            "maxdlcount": brush_config.maxdlcount,
            "include": brush_config.include,
            "exclude": brush_config.exclude,
            "size": brush_config.size,
            "seeder": brush_config.seeder,
            "pubtime": brush_config.pubtime,
            "seed_time": brush_config.seed_time,
            "seed_ratio": brush_config.seed_ratio,
            "seed_size": brush_config.seed_size,
            "download_time": brush_config.download_time,
            "seed_avgspeed": brush_config.seed_avgspeed,
            "seed_inactivetime": brush_config.seed_inactivetime,
            "up_speed": brush_config.up_speed,
            "dl_speed": brush_config.dl_speed,
            "save_path": brush_config.save_path,
            "clear_task": brush_config.clear_task,
            "archive_task": brush_config.archive_task,
            "except_tags": brush_config.except_tags,
            "except_subscribe": brush_config.except_subscribe,
            "brush_sequential": brush_config.brush_sequential,
            "proxy_download": brush_config.proxy_download
        }
        
        # 使用update_config方法或其等效方法更新配置
        self.update_config(config_mapping)

    def __setup_downloader(self):
        """
        根据下载器类型初始化下载器实例
        """
        brush_config = self.__get_brush_config()
        
        if brush_config.downloader == "qbittorrent":
            self.qb = Qbittorrent()
            if self.qb.is_inactive():
                self.__log_and_notify_error("站点刷流任务出错：Qbittorrent未连接")
                return False
            
        elif brush_config.downloader == "transmission":
            self.tr = Transmission()
            if self.tr.is_inactive():
                self.__log_and_notify_error("站点刷流任务出错：Transmission未连接")
                return False
            
        return True

    def __get_downloader(self, dtype: str) -> Optional[Union[Transmission, Qbittorrent]]:
        """
        根据类型返回下载器实例
        """
        if dtype == "qbittorrent":
            return self.qb
        elif dtype == "transmission":
            return self.tr
        else:
            return None

    def __download(self, torrent: TorrentInfo) -> Optional[str]:
        """
        添加下载任务
        """
        brush_config = self.__get_brush_config()

        # 上传限速
        up_speed = int(brush_config.up_speed) if brush_config.up_speed else None
        # 下载限速
        down_speed = int(brush_config.dl_speed) if brush_config.dl_speed else None
        # 保存地址
        download_dir=brush_config.save_path or None
        
        if brush_config.downloader == "qbittorrent":
            if not self.qb:
                return None
            # 限速值转为bytes
            up_speed = up_speed * 1024 if up_speed else None
            down_speed = down_speed * 1024 if down_speed else None
            # 生成随机Tag
            tag = StringUtils.generate_random_str(10)
            torrent_content = torrent.enclosure
            if brush_config.proxy_download:
                request = RequestUtils(cookies=torrent.site_cookie, ua=torrent.site_ua)
                response = request.get_res(url=torrent.enclosure)
                if response and response.ok:
                    torrent_content = response.content
                else:
                    logger.error('代理下载种子失败，继续尝试传递种子地址到下载器进行下载')
            if torrent_content:
                state = self.qb.add_torrent(content=torrent_content,
                                            download_dir=download_dir,
                                            cookie=torrent.site_cookie,
                                            tag=["已整理", "刷流", tag],
                                            upload_limit=up_speed,
                                            download_limit=down_speed)
            if not state:
                return None
            else:
                # 获取种子Hash
                torrent_hash = self.qb.get_torrent_id_by_tag(tags=tag)
                if not torrent_hash:
                    logger.error(f"{brush_config.downloader} 获取种子Hash失败")
                    return None
            return torrent_hash
        
        elif brush_config.downloader == "transmission":
            if not self.tr:
                return None
            # 添加任务
            torrent_content = torrent.enclosure
            if brush_config.proxy_download:
                request = RequestUtils(cookies=torrent.site_cookie, ua=torrent.site_ua)
                response = request.get_res(url=torrent.enclosure)
                if response and response.ok:
                    torrent_content = response.content
                else:
                    logger.error('代理下载种子失败，继续尝试传递种子地址到下载器进行下载')
            if torrent_content:
                torrent = self.tr.add_torrent(content=torrent.enclosure,
                                          download_dir=download_dir,
                                          cookie=torrent.site_cookie,
                                          labels=["已整理", "刷流"])
                if not torrent:
                    return None
                else:
                    if brush_config.up_speed or brush_config.dl_speed:
                        self.tr.change_torrent(hash_string=torrent.hashString,
                                            upload_limit=up_speed,
                                            download_limit=down_speed)
                    return torrent.hashString
        return None

    def __get_hash(self, torrent: Any):
        """
        获取种子hash
        """
        brush_config = self.__get_brush_config()
        try:
            return torrent.get("hash") if brush_config.downloader == "qbittorrent" else torrent.hashString
        except Exception as e:
            print(str(e))
            return ""
        
    def __get_all_hashes(self, torrents):
        """
        获取torrents列表中所有种子的Hash值

        :param torrents: 包含种子信息的列表
        :return: 包含所有Hash值的列表
        """
        brush_config = self.__get_brush_config()
        try:
            all_hashes = []
            for torrent in torrents:
                # 根据下载器类型获取Hash值
                hash_value = torrent.get("hash") if brush_config.downloader == "qbittorrent" else torrent.hashString
                if hash_value:
                    all_hashes.append(hash_value)
            return all_hashes
        except Exception as e:
            print(str(e))
            return []

    def __get_label(self, torrent: Any):
        """
        获取种子标签
        """
        brush_config = self.__get_brush_config()
        try:
            return [str(tag).strip() for tag in torrent.get("tags").split(',')] \
                if brush_config.downloader == "qbittorrent" else torrent.labels or []
        except Exception as e:
            print(str(e))
            return []

    def __get_torrent_info(self, torrent: Any) -> dict:
        """
        获取种子信息
        """
        date_now = int(time.time())
        brush_config = self.__get_brush_config()
        # QB
        if brush_config.downloader == "qbittorrent":
            """
            {
              "added_on": 1693359031,
              "amount_left": 0,
              "auto_tmm": false,
              "availability": -1,
              "category": "tJU",
              "completed": 67759229411,
              "completion_on": 1693609350,
              "content_path": "/mnt/sdb/qb/downloads/Steel.Division.2.Men.of.Steel-RUNE",
              "dl_limit": -1,
              "dlspeed": 0,
              "download_path": "",
              "downloaded": 67767365851,
              "downloaded_session": 0,
              "eta": 8640000,
              "f_l_piece_prio": false,
              "force_start": false,
              "hash": "116bc6f3efa6f3b21a06ce8f1cc71875",
              "infohash_v1": "116bc6f306c40e072bde8f1cc71875",
              "infohash_v2": "",
              "last_activity": 1693609350,
              "magnet_uri": "magnet:?xt=",
              "max_ratio": -1,
              "max_seeding_time": -1,
              "name": "Steel.Division.2.Men.of.Steel-RUNE",
              "num_complete": 1,
              "num_incomplete": 0,
              "num_leechs": 0,
              "num_seeds": 0,
              "priority": 0,
              "progress": 1,
              "ratio": 0,
              "ratio_limit": -2,
              "save_path": "/mnt/sdb/qb/downloads",
              "seeding_time": 615035,
              "seeding_time_limit": -2,
              "seen_complete": 1693609350,
              "seq_dl": false,
              "size": 67759229411,
              "state": "stalledUP",
              "super_seeding": false,
              "tags": "",
              "time_active": 865354,
              "total_size": 67759229411,
              "tracker": "https://tracker",
              "trackers_count": 2,
              "up_limit": -1,
              "uploaded": 0,
              "uploaded_session": 0,
              "upspeed": 0
            }
            """
            # ID
            torrent_id = torrent.get("hash")
            # 标题
            torrent_title = torrent.get("name")
            # 下载时间
            if (not torrent.get("added_on")
                    or torrent.get("added_on") < 0):
                dltime = 0
            else:
                dltime = date_now - torrent.get("added_on")
            # 做种时间
            if (not torrent.get("completion_on")
                    or torrent.get("completion_on") < 0):
                seeding_time = 0
            else:
                seeding_time = date_now - torrent.get("completion_on")
            # 分享率
            ratio = torrent.get("ratio") or 0
            # 上传量
            uploaded = torrent.get("uploaded") or 0
            # 平均上传速度 Byte/s
            if dltime:
                avg_upspeed = int(uploaded / dltime)
            else:
                avg_upspeed = uploaded
            # 已未活动 秒
            if (not torrent.get("last_activity")
                    or torrent.get("last_activity") < 0):
                iatime = 0
            else:
                iatime = date_now - torrent.get("last_activity")
            # 下载量
            downloaded = torrent.get("downloaded")
            # 种子大小
            total_size = torrent.get("total_size")
            # 添加时间
            add_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(torrent.get("added_on") or 0))
            # 种子标签
            tags = torrent.get("tags")
        # TR
        else:
            # ID
            torrent_id = torrent.hashString
            # 标题
            torrent_title = torrent.name
            # 做种时间
            if (not torrent.date_done
                    or torrent.date_done.timestamp() < 1):
                seeding_time = 0
            else:
                seeding_time = date_now - int(torrent.date_done.timestamp())
            # 下载耗时
            if (not torrent.date_added
                    or torrent.date_added.timestamp() < 1):
                dltime = 0
            else:
                dltime = date_now - int(torrent.date_added.timestamp())
            # 下载量
            downloaded = int(torrent.total_size * torrent.progress / 100)
            # 分享率
            ratio = torrent.ratio or 0
            # 上传量
            uploaded = int(downloaded * torrent.ratio)
            # 平均上传速度
            if dltime:
                avg_upspeed = int(uploaded / dltime)
            else:
                avg_upspeed = uploaded
            # 未活动时间
            if (not torrent.date_active
                    or torrent.date_active.timestamp() < 1):
                iatime = 0
            else:
                iatime = date_now - int(torrent.date_active.timestamp())
            # 种子大小
            total_size = torrent.total_size
            # 添加时间
            add_time = time.strftime('%Y-%m-%d %H:%M:%S',
                                     time.localtime(torrent.date_added.timestamp() if torrent.date_added else 0))
            # 种子标签
            tags = torrent.get("tags")

        return {
            "hash": torrent_id,
            "title": torrent_title,
            "seeding_time": seeding_time,
            "ratio": ratio,
            "uploaded": uploaded,
            "downloaded": downloaded,
            "avg_upspeed": avg_upspeed,
            "iatime": iatime,
            "dltime": dltime,
            "total_size": total_size,
            "add_time": add_time,
            "tags": tags
        }

    def __log_and_notify_error(self, message):
        """
        记录错误日志并发送系统通知
        """
        logger.error(message)
        self.systemmessage.put(message)

    def __send_delete_message(self, site_name: str, torrent_title: str, reason: str):
        """
        发送删除种子的消息
        """
        brush_config = self.__get_brush_config()
        if not brush_config.notify:
            return
        self.chain.post_message(Notification(
            mtype=NotificationType.SiteMessage,
            title=f"【刷流任务删种】",
            text=f"站点：{site_name}\n"
                 f"标题：{torrent_title}\n"
                 f"原因：{reason}"
        ))

    def __send_add_message(self, torrent: TorrentInfo):
        """
        发送添加下载的消息
        """
        brush_config = self.__get_brush_config()
        if not brush_config.notify:
            return
        msg_text = ""
        if torrent.site_name:
            msg_text = f"站点：{torrent.site_name}"
        if torrent.title:
            msg_text = f"{msg_text}\n标题：{torrent.title}"
        if torrent.size:
            if str(torrent.size).replace(".", "").isdigit():
                size = StringUtils.str_filesize(torrent.size)
            else:
                size = torrent.size
            msg_text = f"{msg_text}\n大小：{size}"
        if torrent.pubdate:
            msg_text = f"{msg_text}\n发布时间：{torrent.pubdate}"
        if torrent.seeders:
            msg_text = f"{msg_text}\n做种数：{torrent.seeders}"
        if torrent.volume_factor:
            msg_text = f"{msg_text}\n促销：{torrent.volume_factor}"
        if torrent.hit_and_run:
            msg_text = f"{msg_text}\nHit&Run：是"

        self.chain.post_message(Notification(
            mtype=NotificationType.SiteMessage,
            title="【刷流任务种子下载】",
            text=msg_text
        ))

    def __get_torrents_size(self) -> int:
        """
        获取任务中的种子总大小
        """
        # 读取种子记录
        task_info = self.get_data("torrents") or {}
        if not task_info:
            return 0
        total_size = sum([task.get("size") or 0 for task in task_info.values()])
        return total_size

    def __get_downloader_info(self) -> schemas.DownloaderInfo:
        """
        获取下载器实时信息（所有下载器）
        """
        ret_info = schemas.DownloaderInfo()

        # Qbittorrent
        if self.qb:
            info = self.qb.transfer_info()
            if info:
                ret_info.download_speed += info.get("dl_info_speed")
                ret_info.upload_speed += info.get("up_info_speed")
                ret_info.download_size += info.get("dl_info_data")
                ret_info.upload_size += info.get("up_info_data")

        # Transmission
        if self.tr:
            info = self.tr.transfer_info()
            if info:
                ret_info.download_speed += info.download_speed
                ret_info.upload_speed += info.upload_speed
                ret_info.download_size += info.current_stats.downloaded_bytes
                ret_info.upload_size += info.current_stats.uploaded_bytes

        return ret_info

    def __get_downloading_count(self) -> int:
        """
        获取正在下载的任务数量
        """
        brush_config = self.__get_brush_config()
        downlader = self.__get_downloader(brush_config.downloader)
        if not downlader:
            return 0
        torrents = downlader.get_downloading_torrents()
        return len(torrents) or 0

    def __get_pubminutes(self, pubdate: str) -> float:
        """
        将字符串转换为时间，并计算与当前时间差）（分钟）
        """
        try:
            if not pubdate:
                return 0
            pubdate = pubdate.replace("T", " ").replace("Z", "")
            pubdate = datetime.strptime(pubdate, "%Y-%m-%d %H:%M:%S")
            now = datetime.now()
            return (now - pubdate).total_seconds() // 60
        except Exception as e:
            print(str(e))
            return 0
    
    def __adjust_site_pubminutes(self, pub_minutes: float, torrent: TorrentInfo) -> float:
        """
        处理部分站点的时区逻辑
        """
        try:
            if not torrent:
                return pub_minutes
                        
            if torrent.site_name == "我堡":
                # 获取当前时区的UTC偏移量（以秒为单位）
                utc_offset_seconds = time.timezone

                # 将UTC偏移量转换为分钟
                utc_offset_minutes = utc_offset_seconds / 60
                
                # 增加UTC偏移量到pub_minutes
                adjusted_pub_minutes = pub_minutes + utc_offset_minutes
                            
                return adjusted_pub_minutes
            
            return pub_minutes
        except Exception as e:
            logger.error(str(e))
            return 0

    def __filter_torrents_by_tag(self, torrents: List[Any], exclude_tag: str) -> List[Any]:
        """
        根据标签过滤torrents
        """
        filter_torrents = []
        for torrent in torrents:
            # 使用 __get_label 方法获取每个 torrent 的标签列表
            labels = self.__get_label(torrent)
            # 如果排除的标签不在这个列表中，则添加到过滤后的列表
            if exclude_tag not in labels:
                filter_torrents.append(torrent)
        return filter_torrents

    def __get_subscribe_titles(self) -> Set[str]:
        """
        获取当前订阅的所有标题，返回一个不包含None的集合
        """
        self.subscribeoper = SubscribeOper()
        subscribes = self.subscribeoper.list()

        # 使用 filter() 函数筛选出有 'name' 属性且该属性值不为 None 的 Subscribe 对象
        # 然后使用 map() 函数获取每个对象的 'name' 属性值
        # 最后，使用 set() 函数将结果转换为集合，自动去除重复项和 None
        subscribe_titles = set(filter(None, map(lambda sub: getattr(sub, 'name', None), subscribes)))

        # 返回不包含 None 的名称集合
        return subscribe_titles
    
    def __filter_torrents_contains_subscribe(self, torrents : Any):
        subscribe_titles = self.__get_subscribe_titles()
        logger.info(f"当前订阅的名称集合为：{subscribe_titles}")

        # 初始化两个列表，一个用于收集未被排除的种子，一个用于记录被排除的种子
        included_torrents = []
        excluded_torrents = []

        # 单次遍历处理
        for torrent in torrents:
            if any(title in torrent.title or title in torrent.description for title in subscribe_titles):
                # 如果种子的标题或描述包含订阅标题中的任一项，则记录为被排除
                excluded_torrents.append(torrent)
                logger.info(f"命中订阅内容，排除种子：{torrent.title}|{torrent.description}")
            else:
                # 否则，收集为未被排除的种子
                included_torrents.append(torrent)
        
        if not excluded_torrents:
            logger.info(f"没有命中订阅内容，不需要排除种子")
         
        # 返回未被排除的种子列表
        return included_torrents
    
    def __bytes_to_gb(self, size_in_bytes: int) -> float:
        """
        将字节单位的大小转换为千兆字节（GB）。

        :param size_in_bytes: 文件大小，单位为字节。
        :return: 文件大小，单位为千兆字节（GB）。
        """
        return size_in_bytes / (1024 ** 3)
    
    def __is_number_or_range(self, value):
        """
        检查字符串是否表示单个数字或数字范围（如'5'或'5-10'）
        """
        return bool(re.match(r"^\d+(-\d+)?$", value))
    
    def __is_number(self, value):
        """
        检查给定的值是否可以被转换为数字（整数或浮点数）
        """
        try:
            float(value)
            return True
        except ValueError:
            return False

    def __calculate_seeding_torrents_size(self, torrent_tasks: Dict[str, dict]) -> int:
        """
        计算保种种子体积
        """
        return sum(task.get("size", 0) for task in torrent_tasks.values() if not task.get("deleted", False))
    
    def __archive_tasks(self):
        """
        归档已经删除的种子数据
        """
        
        torrent_tasks: Dict[str, dict] = self.get_data("torrents") or {}

        # 用于存储已删除的数据
        archived_tasks: Dict[str, dict] = self.get_data("archived_torrents") or {}
        
        # 准备一个列表，记录所有需要从原始数据中删除的键
        keys_to_delete = []
        
        # 遍历所有 torrent 条目
        for key, value in torrent_tasks.items():
            # 检查是否标记为已删除
            if value.get("deleted"):
                # 如果是，加入到归档字典中
                archived_tasks[key] = value
                # 记录键，稍后删除
                keys_to_delete.append(key)
        
        # 从原始字典中移除已删除的条目
        for key in keys_to_delete:
            del torrent_tasks[key]
        
        self.save_data("archived_torrents", archived_tasks)
        self.save_data("torrents", torrent_tasks)