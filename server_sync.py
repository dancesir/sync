# -*- encoding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution    
#    Copyright (C) 2004-2009 Tiny SPRL (<http://tiny.be>). All Rights Reserved
#    $Id$
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp.osv import fields, osv, orm
import logging

SHARE_TYPE = [
    ('update', u'更新'),
    ('new', u'新建'),
]

_logger = logging.getLogger(__name__)

class server_sync(osv.osv):
    _name = 'server.sync'

    _columns = {
        'name': fields.char(u'服务器名称', size=100, required='True'),
        'code': fields.char(u'编码', size=100, required='True'),
        'ip_address': fields.char(u'IP地址', size=100, required='True'),
        'port': fields.integer(u'端口', size=10, required='True'),
        'db_name': fields.char(u'数据库名', size=100, required='True'),
        'user_name': fields.char(u'用户名', size=100, required='True',),
        'user_password': fields.char(u'密码',  required='True'),
        }

    _sql_constraints = [
        ('unique_name', 'unique (code)', u'服务器名不能重复'),
    ]


class server_sync_log(osv.osv):
    _name = 'server.sync.log'
    _order = "date desc"

    _columns = {
        'name': fields.char(u'日志',readonly=True),
        'server_id':fields.many2one('server.sync', u'目标服务器', readonly=True),
        'date': fields.datetime(u'日期', readonly=True),
        'act_user': fields.many2one('res.users', u'创建人', readonly=True),
        'description': fields.text(u'描述', readonly=True ),
        'local_id': fields.integer(u'本地ID', readonly=True),
        'remote_id': fields.integer(u'远程ID', readonly=True),
        'model_name': fields.char(u'模块名', readonly=True),
        'sync_type': fields.selection(SHARE_TYPE, u'同步类型',readonly=True),
    }



# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
