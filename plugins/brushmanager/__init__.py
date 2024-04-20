from typing import Any, List, Dict, Tuple, Optional, Union

from app.core.plugin import PluginManager
from app.log import logger
from app.modules.qbittorrent import Qbittorrent
from app.modules.transmission import Transmission
from app.plugins import _PluginBase


class BrushManager(_PluginBase):
    # 插件名称
    plugin_name = "刷流种子整理"
    # 插件描述
    plugin_desc = "针对刷流种子进行整理操作。"
    # 插件图标
    plugin_icon = "https://github.com/InfinityPacer/MoviePilot-Plugins/raw/main/icons/brushtmanager.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "InfinityPacer"
    # 作者主页
    author_url = "https://github.com/InfinityPacer"
    # 插件配置项ID前缀
    plugin_config_prefix = "brushmanager_"
    # 加载顺序
    plugin_order = 28
    # 可使用的用户级别
    auth_level = 2

    # region 私有属性

    # 插件Manager
    pluginmanager = None
    # QB分类数据源
    _source_categories = None
    # 目录地址数据源
    _source_paths = None
    # 选择的刷流插件
    _brush_plugin = None
    # 下载器
    _downloader = None
    # 移动目录
    _move_path = None
    # 种子分类
    _category = None
    # 开启通知
    _notify = None
    # 自动分类
    _auto_category = None
    # 添加MP标签
    _mp_tag = None
    # 移除刷流标签
    _remove_brush_tag = None

    # endregion

    def init_plugin(self, config: dict = None):
        self.pluginmanager = PluginManager()

        if not config:
            logger.info("刷流种子整理出错，无法获取插件配置")
            return False

        self._source_paths = config.get("source_paths", None)
        self._source_categories = config.get("source_categories", None)
        self._brush_plugin = config.get("brush_plugin", None)
        self._downloader = config.get("downloader", None)
        self._move_path = config.get("move_path", None)
        self._category = config.get("category", None)
        self._notify = config.get("notify", False)
        self._auto_category = config.get("auto_category", False)
        self._mp_tag = config.get("mp_tag", False)
        self._remove_brush_tag = config.get("remove_brush_tag", False)

        self.__update_config(config=config)

        # 停止现有任务
        self.stop_service()

        if not self._downloader:
            self.__log_and_notify_error("没有配置下载器")
            return

        if not self.__setup_downloader():
            return

    def get_state(self):
        pass

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        # 已安装的刷流插件
        plugin_options = self.__get_plugin_options()
        path_options = self.__get_display_options(self._source_categories)
        category_options = self.__get_display_options(self._source_paths)
        torrent_options = self.__get_torrent_options()

        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VTabs',
                        'props': {
                            'model': '_tabs',
                            'fixed-tabs': True
                        },
                        'content': [
                            {
                                'component': 'VTab',
                                'props': {
                                    'value': 'base_tab'
                                },
                                'text': '基本配置'
                            }, {
                                'component': 'VTab',
                                'props': {
                                    'value': 'data_tab'
                                },
                                'text': '数据配置'
                            }
                        ]
                    },
                    {
                        'component': 'VWindow',
                        'props': {
                            'model': '_tabs',
                            'style': {
                                'padding-top': '24px',
                                'padding-bottom': '24px',
                            },
                        },
                        'content': [
                            {
                                'component': 'VWindowItem',
                                'props': {
                                    'value': 'base_tab'
                                },
                                'content': [
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
                                                            'chips': True,
                                                            'multiple': True,
                                                            'model': 'torrents',
                                                            'label': '选择种子',
                                                            'items': torrent_options,
                                                            "clearable": True,
                                                            'menu-props': {
                                                                'max-width': '-1px'
                                                            }
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
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'move_path',
                                                            'label': '移动目录',
                                                            'items': path_options,
                                                            "clearable": True
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
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'category',
                                                            'label': '种子分类',
                                                            'items': category_options,
                                                            "clearable": True
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
                                                    'md': 3
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
                                                    'md': 3
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'auto_category',
                                                            'label': '自动分类管理',
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 3
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'mp_tag',
                                                            'label': '添加MP标签',
                                                        }
                                                    }
                                                ]
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 3
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'remove_brush_tag',
                                                            'label': '移除刷流标签',
                                                        }
                                                    }
                                                ]
                                            },
                                        ]
                                    }
                                ]
                            },
                            {
                                'component': 'VWindowItem',
                                'props': {
                                    'value': 'data_tab'
                                },
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    "cols": 12,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSelect',
                                                        'props': {
                                                            'model': 'brush_plugin',
                                                            'label': '刷流插件',
                                                            'items': plugin_options
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
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextarea',
                                                        'props': {
                                                            'model': 'source_categories',
                                                            'label': '分类配置',
                                                            'placeholder': '仅支持QB，每一行一个分类，格式为：QB分类名称，分类名称'
                                                                           ':QB分类名称，参考如下：\nMovie\n电影:Movie'
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
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextarea',
                                                        'props': {
                                                            'model': 'source_paths',
                                                            'label': '目录配置',
                                                            'placeholder': '每一行一个目录，格式为：目录地址，目录名称:目录地址，'
                                                                           '参考如下：\n/volume1/Media/Movie'
                                                                           '\n电影:/volume1/Media/Movie'
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            },
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
                                            'text': '请先在数据配置中初始化数据源，点击保存后再打开插件选择种子进行整理'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "notify": True,
            "mp_tag": True,
            "remove_brush_tag": True,
            "auto_category": True
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass

    def __update_config(self, config: dict):
        """
        更新配置
        """
        # 列出要排除的键
        exclude_keys = ['torrents']

        # 使用字典推导创建一个新字典，排除在 exclude_keys 列表中的键
        filtered_config = {key: value for key, value in config.items() if key not in exclude_keys}

        # 使用 filtered_config 进行配置更新
        self.update_config(filtered_config)

    def __get_torrent_options(self) -> List[dict]:
        # 检查刷流插件是否已选择
        if not self._brush_plugin:
            logger.info("刷流插件尚未选择，无法获取到刷流任务")
            return []

        # 获取刷流任务数据
        torrent_tasks = self.get_data("torrents", self._brush_plugin)
        if not torrent_tasks:
            logger.info(f"刷流插件：{self._brush_plugin}，没有获取到刷流任务")
            return []

        # 初始化任务选项列表
        torrent_options = []

        # 解析任务数据
        for task_id, task_info in torrent_tasks.items():
            # 检查任务是否已被删除
            if task_info.get('deleted', False):
                continue  # 如果已被删除，则跳过这个任务

            # 格式化描述和标题
            description = task_info.get('description')
            title = f"{description} | {task_info['title']}" if description else task_info['title']

            torrent_options.append({
                "title": title,
                "value": task_id,
                "name": task_info['title']
            })

        # 根据创建时间排序，确保所有元素都有时间戳
        torrent_options.sort(key=lambda x: torrent_tasks[x['value']].get('time', 0), reverse=True)

        # 添加序号到标题
        for index, option in enumerate(torrent_options, start=1):
            option["title"] = f"{index}. {option['title']}"

        # 日志记录获取的任务
        logger.info(f"刷流插件：{self._brush_plugin}，共获取到 {len(torrent_options)} 个刷流任务")

        return torrent_options

    def __get_plugin_options(self) -> List[dict]:
        # 获取正在运行的插件选项
        running_plugins = self.pluginmanager.get_running_plugin_ids()

        # 需要检查的插件名称
        filter_plugins = {"BrushFlow", "BrushFlowLowFreq"}

        # 获取本地插件列表
        local_plugins = self.pluginmanager.get_local_plugins()

        # 初始化插件选项列表
        plugin_options = []

        # 从本地插件中筛选出符合条件的插件
        for local_plugin in local_plugins:
            if local_plugin.id in running_plugins and local_plugin.id in filter_plugins:
                plugin_options.append({
                    "title": f"{local_plugin.plugin_name} v{local_plugin.plugin_version}",
                    "value": local_plugin.id,
                    "name": local_plugin.plugin_name
                })

        # 重新编号，保证显示为 1. 2. 等
        for index, option in enumerate(plugin_options, start=1):
            option["title"] = f"{index}. {option['title']}"

        return plugin_options

    @staticmethod
    def __get_display_options(source: str) -> List[dict]:
        # 检查是否有可用的源数据
        if not source:
            return []

        # 将源字符串分割为单独的列表并去除每一项的前后空格
        categories = [category.strip() for category in source.split("\n") if category.strip()]

        # 初始化分类选项列表
        category_options = []

        # 遍历分割后且清理过的分类数据，格式化并创建包含title, value, name的字典
        for category in categories:
            parts = category.split(":")
            if len(parts) > 1:
                display_name, name = parts[0].strip(), parts[1].strip()
            else:
                display_name = name = parts[0].strip()

            # 将格式化后的数据添加到列表
            category_options.append({
                "title": display_name,
                "value": name,
                "name": display_name
            })

        return category_options

    def __setup_downloader(self):
        """
        根据下载器类型初始化下载器实例
        """
        if self._downloader == "qbittorrent":
            self.qb = Qbittorrent()
            if self.qb.is_inactive():
                self.__log_and_notify_error("qBittorrent未连接")
                return False

        elif self._downloader == "transmission":
            self.tr = Transmission()
            if self.tr.is_inactive():
                self.__log_and_notify_error("Transmission未连接")
                return False

        return True

    def __get_downloader(self) -> Optional[Union[Transmission, Qbittorrent]]:
        """
        根据类型返回下载器实例
        """
        if self._downloader == "qbittorrent":
            return self.qb
        elif self._downloader == "transmission":
            return self.tr
        else:
            return None

    def __log_and_notify_error(self, message):
        """
        记录错误日志并发送系统通知
        """
        logger.error(message)
        self.systemmessage.put(message)
