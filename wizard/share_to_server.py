# -*- coding: utf-8 -*-
##############################################################################
#   0：检查远程服务器是否安装同步模块
#   1：检查本地需要同步的记录所在模块的字段和远程服务器是否一致
#   2：读取需要同步的数据
#   3：根据同步类型做相应检查：
#       A：更新：
#           一：检查该记录在本地是否有同步记录
#           二：如果该记录在本地没有同步记录，检查远程服务器是否有同步到本机的记录
#           三：根据数据库约束查找?????
#           四：以上都没有，直接通过本地ID查找服务器上是否存在对应ID
#       B：新建：
#   4：同步数据转换，日志详情创建
#   5：远程服务器更新或新建需要同步的数据
#   6：日志数据创建，日志数据写入或更新
##############################################################################

import xmlrpclib
from datetime import datetime
from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT as DTF
from openerp.tools import config
from openerp.osv import fields, osv, expression
from openerp.tools.translate import _
from openerp.exceptions import Warning
from openerp.addons.server_sync.server_sync import SHARE_TYPE as SHARE_TYPE
import threading
import re
import logging
import cProfile

_logger = logging.getLogger(__name__)


class RPCProxyOne(object):
    def __init__(self, server, ressource):

        self.server = server

        host = ''.join(server.ip_address.split())
        # port = ''.join(server.port.split())
        self.dbname = ''.join(server.db_name.split())
        username = ''.join(server.user_name.split())
        self.password = ''.join(server.user_password.split())
        try:
            local_url = 'http://%s:%d/xmlrpc/common' % (host, server.port)
            rpc = xmlrpclib.ServerProxy(local_url)
            self.uid = rpc.login(self.dbname, username, self.password)
            local_url = 'http://%s:%d/xmlrpc/object' % (host, server.port)
            self.rpc = xmlrpclib.ServerProxy(local_url)
        except Exception, e:
            _logger.info(u'服务器连接失败：%s' % (e))
            raise osv.except_osv(_(u'警告'), _(u'远程服务器连接失败！'))
        self.ressource = ressource

    def __getattr__(self, name):
        if name == 'fields_get':
            return lambda cr, uid, *args, **kwargs: self.rpc.execute_kw(self.dbname, self.uid, self.password,
                                                                        self.ressource, name, *args, **kwargs)
        else:
            return lambda cr, uid, *args, **kwargs: self.rpc.execute(self.dbname, self.uid, self.password,
                                                                     self.ressource, name, *args)


class RPCProxy(object):
    def __init__(self, server):
        self.server = server

    def get(self, ressource):
        return RPCProxyOne(self.server, ressource)


class share_to_server(osv.osv_memory):
    _name = 'share.to.server'

    _columns = {
        'server_name': fields.many2many('server.sync', string=u'选择服务器', required=True),
        'share_type': fields.selection(SHARE_TYPE, string=u'共享信息方式')
    }

    _defaults = {
        'share_type': 'update',
    }



    # 检测远程服务器是否安装同步模块
    def check_module(self, cr, uid, remote_pool):
        module = remote_pool.get("ir.module.module")
        module_id = module.search(cr, uid, [("name", "ilike", "server_sync"), ('state', '=', 'installed')])
        if not module_id:
            raise osv.except_osv(_(u'警告'), _(u'新建和更新记录需要同时在本地和远程服务器安装server_sync模块'))

    # 检查数据表字段一致性，返回：
    # 字段名，字段类型（key:type），关联模块名（key:relation），关联字段（key:relation_field）
    def check_table(self, cr, uid, remote_pool, model_osv, context=None):
        local_fileds = model_osv.fields_get(cr, uid, context=context, attributes=['type', 'relation', 'relation_field'])
        server_fields = remote_pool.get(str(model_osv)).fields_get(cr, uid, [], {
            'attributes': ['type', 'relation', 'relation_field']})

        local = sorted(local_fileds.iteritems(), key=lambda d: d[0])
        server = sorted(server_fields.iteritems(), key=lambda d: d[0])
        if cmp(local, server) != 0:
            raise osv.except_osv(_(u'警告'), _(u'远程服务器的表结构与本地数据表结构不一致，无法共享数据'))
        else:
            return local_fileds

    # 返回需要共享的数据及相关内容
    # all_vals:所有字段名及对应的数据
    def get_share_values(self, cr, uid, active_ids, active_model, context=None):
        all_vals = {}
        for share_val in self.pool.get(active_model).read(cr, uid, active_ids):
            all_vals[share_val.get('id')] = share_val
        return all_vals

    # 同步日志的详情
    def _vals_pop_log(self, cr, uid, k, v, rel_id, context=None):
        _logger.info(u'与%s字段%s关联的模块%s中没有ID：%s' % (v['type'], k, v['relation'], rel_id))
        description = u'字段%s(类型：%s)关联的模块%s中没有找到匹配的ID：%s,该字段值设为默认值或空\n' % (k, v['type'], v['relation'], rel_id)
        return description

    # 创建或更新同步日志
    def create_sync_log(self, cr, uid, description, local_id, remote_id, local_log_id, active_model, server,
                        sync_type=None, context=None):
        values = {}
        log_obj = self.pool.get('server.sync.log')
        remote_id = isinstance(remote_id, list) and remote_id[0] or remote_id
        name = '%s%s%s%s%s' % (active_model, u'_', local_id, u'_', remote_id)

        values.update({
            'name': name,
            'date': datetime.utcnow().strftime(DTF),
            'act_user': uid,
            'description': description,
            'sync_type': sync_type,
        })
        if not local_log_id:
            values.update({
                'server_id': server.id,
                'local_id': local_id,
                'remote_id': remote_id,
                'model_name': active_model,
            })
            local_log_id = log_obj.create(cr, uid, values, context=context)
        else:
            log_obj.write(cr, uid, local_log_id, values)

        return local_log_id

    # 检查关联字段及数据,数据格式转换,创建同步日志的详情（description）
    def data_transform(self, cr, uid, remote_pool, fileds_relation, vals, local_id, context=None):
        description = ''
        for k, v in fileds_relation.items():

            if v.has_key('relation'):
                if v['relation'].find('property') > 0:
                    vals.pop(k)
                else:
                    if v['type'] in ['one2many'] and vals[k]:
                        # product.product  seller_ids   seller_id?
                        res_id = v.has_key('relation_field') and v['relation_field'] or 'id'
                        for rel_id in vals[k]:
                            result = remote_pool.get(str(v['relation'])).search(cr, uid, [(res_id, '=', local_id),
                                                                                          ('id', '=', rel_id)])
                            if not result:
                                description += self._vals_pop_log(cr, uid, k, v, rel_id, context=context)
                        vals.pop(k)
                    elif v['type'] in ['many2one'] and vals[k]:
                        val_id = isinstance(vals[k], tuple) and vals[k][0] or vals[k]
                        result = remote_pool.get(str(v['relation'])).search(cr, uid, [('id', '=', val_id)])
                        if not result:
                            description += self._vals_pop_log(cr, uid, k, v, val_id, context=None)
                            vals.pop(k)
                        else:
                            vals.update({k: val_id})
                    elif v['type'] in ['many2many'] and vals[k]:
                        for rel_id in vals[k]:
                            result = remote_pool.get(str(v['relation'])).search(cr, uid, [('id', '=', rel_id)])
                            if not result:
                                description += self._vals_pop_log(cr, uid, k, v, rel_id, context=None)
                        vals.update({k: [(6, 0, vals[k])]})
                    else:
                        pass

        return vals, description

    # 记录更新的条件
    # 1: 根据本地同步日志查找远程记录的ID,
    # 2: 本地日志没有同步记录,
    #   A：查找远程服务器server.sync.log同步日志,
    #   B：根据数据库约束查找?????
    #   C：直接查找远程服务器该模块中记录ID,
    def search_remote_id(self, cr, uid, all_vals, remote_pool, model_osv, local_id, remote_server, context=None):
        # local_log_id = False
        log_obj = self.pool.get('server.sync.log')
        common_args = [('model_name', '=', str(model_osv))]
        search_args1 = common_args + [('local_id', '=', local_id), ('server_id', '=', remote_server.id)]
        local_log_id = log_obj.search(cr, uid, args=search_args1, offset=0, limit=1, order='date DESC')
        if local_log_id:
            rem_id = log_obj.browse(cr, uid, local_log_id, context=context).remote_id
            remote_id = remote_pool.get(str(model_osv)).search(cr, uid, [('id', '=', rem_id)])
        else:
            local_host = config.get('db_host')
            local_port = config.get('xmlrpc_port')
            local_dbname = cr.dbname
            search_args2 = [('ip_address', '=', local_host), ('port', '=', local_port), ('db_name', '=', local_dbname)]
            remote_server_id = remote_pool.get('server.sync').search(cr, uid, search_args2)
            search_args3 = common_args + [('remote_id', '=', local_id), ('server_id', 'in', remote_server_id)]
            # replace with search_read
            # remote_log_id = remote_pool.get('server.sync.log').search(cr, uid, search_args3)
            # remote_id = remote_pool.get('server.sync.log').read(cr, uid, remote_log_id, ['local_id'])
            remote_id = remote_pool.get('server.sync.log').search_read(cr, uid, search_args3, ['local_id'], context=context)
            if remote_id:
                return remote_id[0]['local_id'], local_log_id
            else:
                search_args, error_str = self._get_sql_constraint_args(cr, uid, all_vals[local_id], model_osv,
                                                                       context=context)
                remote_id = remote_pool.get(str(model_osv)).search(cr, uid, search_args)
                if remote_id:
                    return remote_id, local_log_id
                else:
                    remote_id = remote_pool.get(str(model_osv)).search(cr, uid, [('id', '=', local_id)])

        return remote_id, local_log_id

    def _get_sql_constraint_args(self, cr, uid, vals, model_osv, context=None):
        search_args = []
        error_str = ''
        constraint_fields = [f for k, f, s in model_osv._sql_constraints if model_osv._sql_constraints]
        for f in constraint_fields:
            # new_f = re.sub(r'\s+', '', f)   #删除字符串的空格
            # 截取 e( 或者 E( 开头，  ) 结尾 中间的字符串，并根据逗号拆分
            for m in re.findall(r"(?<=[(e\()|(E\()][(])(.*)(?=[)])", re.sub(r'\s+', '', f)):
                ms = [ms for ms in re.split('\W+', m) if vals.has_key(ms)]
                for m2 in ms:
                    val = isinstance(vals[m2], tuple) and vals[m2][0] or vals[m2]
                    search_args.append((m2, '=', val))
                    error_str += u'字段%s=%s\n' % (m2, val)
        return search_args, error_str

    # 新建记录时检查数据库约束条件是否满足
    def check_sql_constraint(self, cr, uid, vals, remote_pool, model_osv, context=None):
        remote_id = False
        search_args, error_str = self._get_sql_constraint_args(cr, uid, vals, model_osv, context=context)
        if model_osv._constraints:
            pass
        if len(search_args):
            remote_id = remote_pool.get(str(model_osv)).search(cr, uid, search_args)
        if remote_id:
            _logger.info(u'%s在远程服务器的%s中已经存在，不允许重复' % (error_str, str(model_osv)))
            raise osv.except_osv(_(u'警告'), _(u'%s在远程服务器的%s中已经存在，不允许重复' % (error_str, str(model_osv))))

        return True

    # 上传数据
    def upload_to_server(self, cr, uid, ids, context=None):
        if context is None:
            context = {}

        active_ids = context.get('active_ids')
        active_model = context.get('active_model')
        model_osv = self.pool[active_model]

        share_type = self.browse(cr, uid, ids, context=context).share_type
        remote_server_objs = self.browse(cr, uid, ids, context=context)
        for remote_server in remote_server_objs.server_name:
            # 检测远程服务器是否安装同步模块
            remote_pool = RPCProxy(remote_server)
            self.check_module(cr, uid, remote_pool)
            # 检查数据表字段定义一致性，返回字段名及相关信息fileds_relation
            fileds_relation = self.check_table(cr, uid, remote_pool, model_osv, context=context)
            # 读取需要同步的数据
            all_vals = self.get_share_values(cr, uid, active_ids, active_model, context=context)

            for active_id in active_ids:
                remote_id, local_log_id = self.search_remote_id(cr, uid, all_vals, remote_pool, model_osv, active_id,
                                                                remote_server, context=context)
                if share_type == 'update' and remote_id:
                    vals, description = self.data_transform(cr, uid, remote_pool, fileds_relation, all_vals[active_id],
                                                            active_id, context=context)
                    remote_pool.get(active_model).write(cr, uid, remote_id, vals)
                    self.create_sync_log(cr, uid, description, active_id, remote_id, local_log_id, active_model,
                                         remote_server, sync_type='update', context=None)
                if share_type == 'update' and not remote_id:
                    raise osv.except_osv(_(u'警告'), _(u'远程服务器没找到匹配记录，无法更新'))
                if share_type == 'new':
                    self.check_sql_constraint(cr, uid, all_vals[active_id], remote_pool, model_osv, context=context)
                    vals, description = self.data_transform(cr, uid, remote_pool, fileds_relation, all_vals[active_id],
                                                            active_id, context=context)
                    vals.pop('id')
                    remote_id = remote_pool.get(active_model).create(cr, uid, vals)
                    local_log_id = False
                    self.create_sync_log(cr, uid, description, active_id, remote_id, local_log_id, active_model,
                                         remote_server, sync_type='new', context=None)
    # 多线程
    def upload_to_server_multi_thread(self, cr, uid, ids, context=None):
        threaded_synchronization = threading.Thread(target=self.upload_to_server(cr, uid, ids, context=context))
        threaded_synchronization.run()

#################################################################################################################
