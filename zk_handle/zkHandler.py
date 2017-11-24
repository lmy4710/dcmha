# -*- encoding: utf-8 -*-
'''
@author: xiaozhong
'''
from kazoo.client import KazooClient
import sys,traceback,time,random
sys.path.append("..")
from lib.get_conf import GetConf
import logging
logging.basicConfig(filename='zk_client.log',
                    level=logging.INFO,
                    format  = '%(asctime)s  %(filename)s : %(levelname)s  %(message)s',
                    datefmt='%Y-%m-%d %A %H:%M:%S')


class zkHander(object):
    '''zookeeper系列操作'''
    def __init__(self):
        zk_hosts = GetConf().GetZKHosts()
        self.zk = KazooClient(hosts=zk_hosts)
        self.zk.start()

    def Get(self,path):
        value,stat = self.zk.get(path=path)
        return value
    def GetChildren(self,path):
        return self.zk.get_children(path=path)
    def Exists(self,path):
        return self.zk.exists(path=path)
    def Create(self,**kwargs):
        return self.zk.create(path=kwargs["path"],value=kwargs["value"],sequence=kwargs['seq'],
                              makepath=(kwargs['mp'] if 'mp' in kwargs else False))
    def Set(self,path,value):
        return self.zk.set(path=path,value=value)

    def init_node(self,object):
        node_list = {'mysql': ['lock', 'white', 'meta/host', 'meta/group', 'meta/router', 'online-list', 'master', 'task',
                               'haproxy','watch-down','addition','addition/replication','addition/region','readbinlog-status']}
        for server in node_list:
            for i in node_list[server]:
                node_path = server + '/' + i
                state = self.zk.exists(path=node_path)
                if state is None:
                    object(node_path)

    def InitNode(self):
        '''初始化node'''
        @self.init_node
        def _init_node(node_path):
            self.zk.ensure_path(node_path)

    def SetReadBinlog(self,master_host,value):
        _path = '/mysql/readbinlog-status/{}'.format(master_host.replace('.','-'))
        self.Create(path=_path,value=value,seq=False) if not self.Exists(_path) else None

    def CreateDownTask(self,groupname,addition=None,region=None):
        task_path = GetConf().GetTaskPath() + '/' + groupname
        if self.Exists(task_path) is None:
            time.sleep(random.uniform(0, 1))
            try:
                if addition:
                    task_path += '_'+region
                    self.Create(path=task_path, value=str([groupname, region,'append','dow']), seq=False)   #跨区域同步主机宕机
                else:
                    self.Create(path=task_path,value=str([groupname,'down']),seq=False)
            except:
                logging.info('Existing outage task for  %s' % groupname)
        else:
            logging.info('Existing outage task for  %s' % groupname)

    def CreateWatch(self,host,addition=None,region=None,region_for_groupname=None):
        '''创建watch,触发时写入task节点'''
        online_host_path = GetConf().GetOnlinePath()
        _group_name = self.GetMeta(type='host', name=host)
        group_name = eval(_group_name)['group'] if _group_name else  region_for_groupname
        online_state = self.zk.exists(online_host_path + '/' + host)
        logging.info("master watch : %s" % host)
        if online_state is not None:
            @self.zk.DataWatch(online_host_path + '/' + host)
            def my_func(data, stat):
                if data is None:
                    self.CreateDownTask(group_name,addition=addition,region=region)
                    logging.error('master(%s) has been down!' % (host))
                    self.zk.stop()
                    sys.exit()
        else:
            _name = group_name + '_' + region if region else group_name
            logging.error("this master %s node not exists" % host)
            state = self.Exists(GetConf().GetWatchDown()+'/'+_name)
            self.Create(path=GetConf().GetWatchDown()+'/'+_name,value="master not online",seq=False) if state is None else None
            self.zk.stop()

    def __checklock(self,taskname):
        """循环检查lock是否存在，当不存在时对新master建立监听"""
        import time
        path = GetConf().GetLockPath() + '/' + taskname
        while True:
            state = self.Exists(path)
            if state is None:
                return True
                break
            time.sleep(0.5)

    def CreateLockWatch(self, taskname):
        '''用于任务在其他节点执行，本节点对锁监听，当删除时获取新master启动watch'''
        path = GetConf().GetLockPath() + '/' + taskname

        @self.zk.DataWatch(path)
        def my_func(data, stat):
            if data is None:
                masterhost = self.GetMasterMeta(taskname)
                self.CreateWatch(masterhost)
                sys.exit()

    def CreateChildrenWatch(self,path,func):
        '''任务列表监听'''
        state = self.zk.exists(path=path)
        if state is not None:
            @self.zk.ChildrenWatch(path)
            def my_func(data):
                if data:
                    data.sort()
                    func(data[0])

    def GetWhite(self,groupname):
        '''check 白名单'''
        white_list = self.GetChildren(path='/mysql/white')
        return True if groupname in white_list else False

    def GetMasterGroupHosts(self):
        '''获取当前master列表,启动检查是否有现有的master，如果有直接监控'''
        group_hosts_path = GetConf().GetMasterPath()
        master_list = self.GetChildren(group_hosts_path)
        return master_list if master_list is not None else False

    def GetAddHost(self):
        '''获取是否需要添加的集群，该节点下记录的为集群组名称，不能并发'''
        Lock_root = GetConf().GetLockPath()
        add_host_path = Lock_root + '/add-host'
        state = self.Exists(add_host_path)
        return self.Get(add_host_path) if state is not None else False

    def GetMeta(self,**kwargs):
        '''获取元数据信息'''
        if kwargs['type'] == 'group':
            node_path = GetConf().GetMetaGroup() + '/' + kwargs['name']
            return self.Get(node_path) if self.Exists(node_path) != None else False
        elif kwargs['type'] == 'host':
            node_path = GetConf().GetMetaHost() + '/' + kwargs['name']
            return self.Get(node_path) if self.Exists(node_path) != None else False
        else:
            logging.error("type is error ,only 【group ,host】")
            raise "type is error ,only 【group ,host】"

    def CreateMasterMeta(self,name,host):
        '''创建master信息节点，用于新集群加入'''
        node_path = GetConf().GetMasterPath() + '/' + name
        return self.Create(path=node_path,value=host,seq=False) if self.Exists(node_path) is None else False

    def AlterMasterMeta(self,name,host):
        '''修改master信息节点，用于切换过后修改元数据'''
        node_path = GetConf().GetMasterPath() + '/' + name
        return self.Set(node_path, host) if self.Exists(node_path) is None else False

    def GetMasterMeta(self,groupname):
        '''获取master元数据信息'''
        node_path = GetConf().GetMasterPath() + '/' + groupname
        return self.Get(node_path) if self.Exists(node_path) is not None else False

    def GetOnlineHostAll(self):
        '''获取在线的节点'''
        node_path = GetConf().GetOnlinePath()
        return self.GetChildren(node_path)

    def GetOnlineState(self,host):
        '''获取单个节点在线状态'''
        node_path = GetConf().GetOnlinePath() + '/' + host
        return True if self.Exists(path=node_path) is not None else False

    def SetHaproxyMeta(self,group,reads,master,type=None):
        '''加入及master变动设置haproxy配置信息'''
        node_path = GetConf().GetHaproxy() + '/' + group
        if type is None:
            meta_path = GetConf().GetMetaGroup()
            if reads is None:
                hosts = self.Get(meta_path+'/'+group)
                reads = hosts.split(',')
            _reads = []
            for host in reads:
                host_meta = self.GetMeta(type='host',name=host)
                host_port = '%s:%d' % (host.replace('-','.'),int(eval(host_meta)['port']))
                _reads.append(host_port)
            master_host_meta = self.GetMeta(type='host',name=master)
            _master = '%s:%d' % (master.replace('-','.'),int(eval(master_host_meta)['port']))


            value = '{"read":"%s","write":"%s"}' % (_reads,_master)
            state = self.Exists(node_path)
            if state is None:
                self.Create(path=node_path,value=value,seq=False)
            else:
                self.Set(path=node_path,value=value)
            return True
        else:
            value = '{"read":"%s","write":"%s"}' % (reads,master)
            self.Set(path=node_path, value=value)
            return True

    def GetTaskList(self):
        '''获取任务列表'''
        task_path = GetConf().GetTaskPath()
        task_list = self.GetChildren(path=task_path)
        return task_list if task_list is not None else False

    def GetTaskContent(self,taskname):
        '''获取任务内容'''
        task_path = GetConf().GetTaskPath()
        task_value = self.Get(task_path+'/'+taskname)
        return task_value if task_value is not None else False

    def DeleteTask(self,taskname):
        '''删除任务'''
        task_path = GetConf().GetTaskPath()
        self.zk.delete(task_path+'/'+taskname) if self.Exists(task_path+'/'+taskname) else None

    def DeleteWhite(self,groupname):
        node_path = GetConf().GetWhitePath()
        self.zk.delete(node_path+'/'+groupname) if self.Exists(node_path+'/'+groupname) else None

    def DeleteWatchDown(self,groupname):
        '''清除心跳丢失的节点'''
        watch_down_path = GetConf().GetWatchDown()
        self.zk.delete(watch_down_path+'/'+groupname) if self.Exists(watch_down_path+'/'+groupname) else None

    def SetMasterHost(self,groupname,masterhost):
        '''写入master信息'''
        masterhost_path = GetConf().GetMasterPath() + '/' + groupname
        self.Set(masterhost_path,masterhost) if self.Exists(masterhost_path) is not None else self.Create(path=masterhost_path,value=masterhost,seq=False)

    def OnlineExists(self,host):
        '''判断是否在线'''
        path = GetConf().GetOnlinePath()
        return True if self.Exists(path+'/'+host) else False

    def GetRouter(self,groupname):
        '''获取路由所在'''
        path = GetConf().GetRouter()
        return self.Get(path+'/'+groupname) if self.Exists(path+'/'+groupname) else False

    def SetWatchDown(self,groupname,value):
        path = GetConf().GetWatchDown()
        self.Create(path=path+'/'+groupname+'_send',value=value,seq=False) if self.Exists(path+'/'+groupname+'_send') is None else None

    def SetLockTask(self,taskname):
        '''创建锁文件，用户多点运行server控制任务'''
        path = GetConf().GetLockPath()
        if self.Exists(path=path + '/' + taskname) is None:
            try:
                time.sleep(random.uniform(0, 1))
                self.zk.create(path=path+'/'+taskname,value=b'',ephemeral=False)
                return True
            except Exception,e:
                logging.error(traceback.format_exc())
                return False
        else:
            return False

    def DeleteLockTask(self,taskname):
        path = GetConf().GetLockPath()
        self.zk.delete(path=path+'/'+taskname) if self.Exists(path=path+'/'+taskname) else None

    def close(self):
        self.zk.stop()

'''
from contextlib import closing
with closing(zkHander()) as zkhander:
    value =  zkhander.GetMeta(type='host',name='192-168-212-205')
    print eval(value)['port']'''