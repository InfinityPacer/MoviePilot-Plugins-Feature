from typing import Any, List, Dict, Tuple

from app.core.plugin import PluginManager
from app.log import logger
from app.plugins import _PluginBase
from app.scheduler import Scheduler


class PluginReload(_PluginBase):
    # 插件名称
    plugin_name = "插件重载"
    # 插件描述
    plugin_desc = "支持插件热重载，用于Docker调试"
    # 插件图标
    plugin_icon = "https://github.com/InfinityPacer/MoviePilot-Plugins/raw/main/icons/reload.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "InfinityPacer"
    # 作者主页
    author_url = "https://github.com/InfinityPacer"
    # 插件配置项ID前缀
    plugin_config_prefix = "pluginreload_"
    # 加载顺序
    plugin_order = 99
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _plugin_id = None
    _previous_state = False

    def init_plugin(self, config: dict = None):
        if config:
            self._previous_state = config.get("previous_state", None)
            self._plugin_id = config.get("plugin_id", None)
            if not self._plugin_id:
                self.__update_config()
                return

            self.__reload(plugin_id=self._plugin_id)
            self.__update_config()

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
        # 已安装插件
        local_plugins = PluginManager().get_local_plugins()
        # 遍历 local_plugins，生成插件类型选项
        plugin_options = [{
            "title": "",
            "value": None
        }]

        for local_plugin in local_plugins:
            if local_plugin.id != "PluginReload":
                plugin_options.append({
                    "title": f"{local_plugin.plugin_name} v{local_plugin.plugin_version}",
                    "value": local_plugin.id
                })
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
                                    'cols': 8
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': False,
                                            'model': 'plugin_id',
                                            'label': '插件重载',
                                            'items': plugin_options
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'previous_state',
                                            'label': '记住上一次',
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
                                            'text': '请选择已安装的本地插件热重载，保存后对应插件将会在内存中重新加载'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "plugin_id": "",
            "previous_state": True,
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass

    @staticmethod
    def __reload(plugin_id: str):
        logger.info(f"Starting reload process for plugin: {plugin_id}")

        # 加载插件到内存
        try:
            PluginManager().reload_plugin(plugin_id)
            logger.info(f"Successfully loaded plugin: {plugin_id} into memory")
        except Exception as e:
            logger.error(f"Failed to load plugin: {plugin_id} into memory. Error: {e}")
            return

        # 注册插件服务
        try:
            Scheduler().update_plugin_job(plugin_id)
            logger.info(f"Successfully updated job schedule for plugin: {plugin_id}")
        except Exception as e:
            logger.error(f"Failed to update job schedule for plugin: {plugin_id}. Error: {e}")
            return

        logger.info(f"Completed reload process for plugin: {plugin_id}")

    def __update_config(self):
        """
        更新配置
        """
        config_mapping = {
            "previous_state": self._previous_state
        }
        if self._previous_state:
            config_mapping["plugin_id"] = self._plugin_id

        # 使用update_config方法或其等效方法更新配置
        self.update_config(config_mapping)
