import os
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, List, Dict, Tuple
from urllib.parse import urljoin

from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType

lock = threading.Lock()


class HistoryClear(_PluginBase):
    # 插件名称
    plugin_name = "历史记录清理"
    # 插件描述
    plugin_desc = "一键清理所有历史记录。"
    # 插件图标
    plugin_icon = "https://github.com/InfinityPacer/MoviePilot-Plugins/raw/main/icons/historyclear.png"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "InfinityPacer"
    # 作者主页
    author_url = "https://github.com/InfinityPacer"
    # 插件配置项ID前缀
    plugin_config_prefix = "historyclear_"
    # 加载顺序
    plugin_order = 61
    # 可使用的用户级别
    auth_level = 1

    # region 私有属性

    # 清理历史记录
    _clear_history = None

    # endregion

    def init_plugin(self, config: dict = None):
        if not config:
            return

        self._clear_history = config.get("clear_history", False)
        if not self._clear_history:
            self.__log_and_notify("未开启历史记录清理")
            return

        self.__log_and_notify("已成功备份并清理历史记录")

    def get_state(self) -> bool:
        pass

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
                                    'md': 6
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
                                    'md': 6
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
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '开启通知',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'digest_auth',
                                            'label': '启用Digest认证'
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
                                    'md': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'hostname',
                                            'label': '服务器地址'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'login',
                                            'label': '登录名'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'password',
                                            'label': '登录密码'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '备份周期'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'max_count',
                                            'label': '最大保留备份数'
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
                                            'text': '如备份失败，请检查日志，并确认WebDAV目录存在，如果存在中文字符，可以尝试进行Url编码后备份'
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
            "notify": True
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
        pass

    def stop_service(self):
        """
        退出插件
        """
        pass

    def __clear(self):
        if not self._clear_history:
            return

        try:
            logger.info("开始执行历史记录清理")
            err_msg, success = self.__backup_files_to_local()
            if not success:
                self.__log_and_notify("清理历史记录失败，备份过程中出现异常，请检查日志后重试")



        except Exception as e:
            msg = f"清理历史记录失败，请排查日志，错误：{e}"
            self.__log_and_notify(msg)

    def __backup_files_to_local(self) -> Tuple[str, bool]:
        """
        执行备份到本地路径
        """
        local_file_path = self.__backup_and_zip_file()
        if not local_file_path:
            err_msg = "无法创建备份文件"
            logger.error(err_msg)
            return err_msg, False

        try:
            file_name = os.path.basename(local_file_path)
            config_path = Path(settings.CONFIG_PATH)
            backup_file_path = config_path / self.__class__.__name__ / "Backup" / file_name
            # 确保备份目录存在
            backup_file_path.parent.mkdir(parents=True, exist_ok=True)
            # 复制文件到备份路径
            shutil.copy(local_file_path, backup_file_path)
            logger.info(f"备份文件成功，备份路径为：{backup_file_path}")
        except Exception as e:
            err_msg = f"备份文件失败: {e}"
            logger.error(err_msg)
            return err_msg, False
        finally:
            # 不论上传成功与否都清理本地文件
            if os.path.exists(local_file_path):
                logger.info(f"清理本地临时文件：{local_file_path}")
                os.remove(local_file_path)

        return "", True

    @staticmethod
    def __backup_and_zip_file() -> str:
        """备份文件并压缩成ZIP文件，按指定格式命名"""
        try:
            config_path = Path(settings.CONFIG_PATH)
            current_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            backup_file_name = f"MoviePliot-Backup-{current_time}"
            backup_path = config_path / backup_file_name
            zip_file_path = str(backup_path) + '.zip'

            # 确保备份路径存在
            backup_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"本地临时备份文件夹路径：{backup_path}")

            # 需要备份的文件列表
            backup_files = [
                config_path / "user.db"
            ]

            # 将文件复制到备份文件夹
            for file_path in backup_files:
                if file_path.exists():
                    logger.info(f"正在备份文件: {file_path}")
                    shutil.copy(file_path, backup_path)

            # 打包备份文件夹为ZIP
            logger.info(f"正在压缩备份文件: {zip_file_path}")
            shutil.make_archive(base_name=str(backup_path), format='zip', root_dir=str(backup_path))

            shutil.rmtree(backup_path)  # 删除临时备份文件夹
            logger.info(f"清理本地临时文件夹：{backup_path}")

            return zip_file_path
        except Exception as e:
            logger.error(f"创建备份ZIP文件失败: {e}")
            return ""

    def __log_and_notify(self, message):
        """
        记录日志并发送系统通知
        """
        logger.info(message)
        self.systemmessage.put(message)
