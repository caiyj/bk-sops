# -*- coding: utf-8 -*-
"""
Tencent is pleased to support the open source community by making 蓝鲸智云PaaS平台社区版 (BlueKing PaaS Community
Edition) available.
Copyright (C) 2017-2021 THL A29 Limited, a Tencent company. All rights reserved.
Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
You may obtain a copy of the License at
http://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
"""

import re
import logging

from cryptography.fernet import Fernet

import env
from pipeline_plugins.base.utils.inject import supplier_account_for_business
from pipeline_plugins.variables.utils import find_module_with_relation

from gcloud.utils import cmdb
from gcloud.utils.ip import get_ip_by_regex
from gcloud.conf import settings

__all__ = [
    "cc_get_ips_info_by_str",
    "get_job_instance_url",
    "get_node_callback_url",
    "plat_ip_reg",
    "get_nodeman_job_url",
]

JOB_APP_CODE = "bk_job"

logger = logging.getLogger("root")
get_client_by_user = settings.ESB_GET_CLIENT_BY_USER
ip_re = r"((25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(25[0-5]|2[0-4]\d|[01]?\d\d?)"
plat_ip_reg = re.compile(r"\d+:" + ip_re)
set_module_ip_reg = re.compile(r"[\u4e00-\u9fa5\w]+\|[\u4e00-\u9fa5\w]+\|" + ip_re)
ip_pattern = re.compile(ip_re)


def cc_get_ips_info_by_str(username, biz_cc_id, ip_str, use_cache=True):
    """
    @summary: 从ip_str中匹配出IP信息
    @param username
    @param biz_cc_id
    @param ip_str
    @param use_cache(deprecated)
    @note: 需要兼容的ip_str格式有
        1： IP，纯IP格式
        2： 集群名称|模块名称|IP，集群名称|模块名称|IP  这种格式可以唯一定位到一
            个IP（如果业务把相同IP放到同一模块，还是有问题）
        3： 云区域ID:IP，云区域ID:IP  这种格式可以唯一定位到一个IP，主要是兼容Job组件
            传参需要和获取Job作业模板步骤参数
    @return: {'result': True or False, 'data': [{'InnerIP': ,'HostID': ,
        'Source': , 'SetID': , 'SetName': , 'ModuleID': , 'ModuleName': , 'Sets': , 'Module': },{}]}
    """

    ip_input_list = get_ip_by_regex(ip_str)

    supplier_account = supplier_account_for_business(biz_cc_id)

    ip_list = cmdb.get_business_host_topo(
        username=username,
        bk_biz_id=biz_cc_id,
        supplier_account=supplier_account,
        host_fields=["bk_host_innerip", "bk_host_id", "bk_cloud_id"],
        ip_list=ip_input_list,
    )
    ip_result = []

    # 如果是格式2 集群名称|模块名称|IP
    if set_module_ip_reg.match(ip_str):
        set_module_ip_list = []
        for match in set_module_ip_reg.finditer(ip_str):
            set_module_ip_list.append(match.group())

        for ip_info in ip_list:
            match = False
            for parent_set in ip_info["set"]:
                if match:
                    break

                for parent_module in ip_info["module"]:
                    if match:
                        break

                    topo_ip = "{set}|{module}|{ip}".format(
                        set=parent_set["bk_set_name"],
                        module=parent_module["bk_module_name"],
                        ip=ip_info["host"].get("bk_host_innerip", ""),
                    )

                    if topo_ip in set_module_ip_list:
                        match = True
                        ip_result.append(
                            {
                                "InnerIP": ip_info["host"].get("bk_host_innerip", ""),
                                "HostID": ip_info["host"]["bk_host_id"],
                                "Source": ip_info["host"].get("bk_cloud_id", -1),
                                "SetID": parent_set["bk_set_id"],
                                "SetName": parent_set["bk_set_name"],
                                "ModuleID": parent_module["bk_module_id"],
                                "ModuleName": parent_module["bk_module_name"],
                                "Sets": ip_info["set"],
                                "Modules": ip_info["module"],
                            }
                        )

    # 格式3 云区域ID:IP
    elif plat_ip_reg.match(ip_str):
        plat_ip = []
        for match in plat_ip_reg.finditer(ip_str):
            plat_ip.append(match.group())

        for ip_info in ip_list:
            cloud_id_ip = "{}:{}".format(
                ip_info["host"].get("bk_cloud_id", -1), ip_info["host"].get("bk_host_innerip", ""),
            )
            if cloud_id_ip in plat_ip:
                ip_result.append(
                    {
                        "InnerIP": ip_info["host"].get("bk_host_innerip", ""),
                        "HostID": ip_info["host"]["bk_host_id"],
                        "Source": ip_info["host"].get("bk_cloud_id", -1),
                        "Sets": ip_info["set"],
                        "Modules": ip_info["module"],
                    }
                )

    # 格式1 纯IP格式
    else:
        ip = []
        for match in ip_pattern.finditer(ip_str):
            ip.append(match.group())

        proccessed = set()
        for ip_info in ip_list:
            if ip_info["host"].get("bk_host_innerip", "") in ip and ip_info["host"]["bk_host_id"] not in proccessed:
                ip_result.append(
                    {
                        "InnerIP": ip_info["host"].get("bk_host_innerip", ""),
                        "HostID": ip_info["host"]["bk_host_id"],
                        "Source": ip_info["host"].get("bk_cloud_id", -1),
                        "Sets": ip_info["set"],
                        "Modules": ip_info["module"],
                    }
                )
                proccessed.add(ip_info["host"]["bk_host_id"])

    valid_ip = [ip_info["InnerIP"] for ip_info in ip_result]
    invalid_ip = list(set(ip_input_list) - set(valid_ip))
    result = {
        "result": True,
        "ip_result": ip_result,
        "ip_count": len(ip_result),
        "invalid_ip": invalid_ip,
    }
    return result


def get_job_instance_url(biz_cc_id, job_instance_id):
    url_format = "{}/api_execute/{}"
    return url_format.format(settings.BK_JOB_HOST, job_instance_id)


def get_node_callback_url(node_id):
    f = Fernet(settings.CALLBACK_KEY)
    return "%staskflow/api/nodes/callback/%s/" % (
        env.BKAPP_INNER_CALLBACK_HOST,
        f.encrypt(bytes(node_id, encoding="utf8")).decode(),
    )


def get_module_id_list_by_name(bk_biz_id, username, set_list, service_template_list):
    """
    @summary 根据集群、服务模板名称筛选出符合条件的模块id
    @param username: 执行用户名
    @param bk_biz_id: 业务id
    @param set_list: 集群list
    @param service_template_list: 服务模板list
    @return:
    """
    set_ids = [set_item["bk_set_id"] for set_item in set_list]
    service_template_ids = [service_template_item["id"] for service_template_item in service_template_list]
    # 调用find_module_with_relation接口根据set id list, service_template_id_list查询模块id
    module_id_list = find_module_with_relation(bk_biz_id, username, set_ids, service_template_ids, ["bk_module_id"])
    return module_id_list


def get_nodeman_job_url(instance_id, bk_host_id):
    return "{}/#/task-history/{}/log/host|instance|host|{}".format(settings.BK_NODEMAN_HOST, instance_id, bk_host_id)


def get_difference_ip_list(original_ip_list, ip_list):
    """
    @summary IP存在性校验
    @param original_ip_list: 手动填写的IP列表
    @param ip_list: 查询到的IP列表
    @return:
    """
    input_ip_list = set(get_ip_by_regex(original_ip_list))
    difference_ip_list = set(input_ip_list).difference(set(ip_list))
    return difference_ip_list
