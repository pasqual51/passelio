import errno
import os
from pathlib import Path
import socket
import threading
import paramiko
import pytest
from blobstore import SFTP


@pytest.fixture
def sftp_server(tmp_path):
    root=tmp_path/'server';root.mkdir();(root/'objects').mkdir()
    host_key=paramiko.RSAKey.generate(2048)
    class Auth(paramiko.ServerInterface):
        def check_auth_password(self,username,password):
            return paramiko.AUTH_SUCCESSFUL if (username,password)==('test-user','local-test-password') else paramiko.AUTH_FAILED
        def get_allowed_auths(self,username):return 'password'
        def check_channel_request(self,kind,chanid):
            return paramiko.OPEN_SUCCEEDED if kind=='session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
    class Files(paramiko.SFTPServerInterface):
        def path(self,path):
            result=(root/path.lstrip('/')).resolve()
            if not result.is_relative_to(root):raise OSError(errno.EACCES,'Denied')
            return result
        def stat(self,path):
            try:return paramiko.SFTPAttributes.from_stat(self.path(path).stat())
            except OSError as error:return paramiko.SFTPServer.convert_errno(error.errno)
        lstat=stat
        def open(self,path,flags,attr):
            try:
                fd=os.open(self.path(path),flags,0o600)
                mode='r+b' if flags&os.O_RDWR else 'wb' if flags&os.O_WRONLY else 'rb'
                stream=os.fdopen(fd,mode)
                handle=paramiko.SFTPHandle(flags)
                if flags&os.O_RDWR or not flags&os.O_WRONLY:handle.readfile=stream
                if flags&os.O_RDWR or flags&os.O_WRONLY:handle.writefile=stream
                return handle
            except OSError as error:return paramiko.SFTPServer.convert_errno(error.errno)
        def chattr(self,path,attr):
            try:paramiko.SFTPServer.set_file_attr(str(self.path(path)),attr);return paramiko.SFTP_OK
            except OSError as error:return paramiko.SFTPServer.convert_errno(error.errno)
        def rename(self,old,new):
            try:
                if self.path(new).exists():return paramiko.SFTP_FAILURE
                self.path(old).rename(self.path(new));return paramiko.SFTP_OK
            except OSError as error:return paramiko.SFTPServer.convert_errno(error.errno)
        def remove(self,path):
            try:self.path(path).unlink();return paramiko.SFTP_OK
            except OSError as error:return paramiko.SFTPServer.convert_errno(error.errno)
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(10);listener.settimeout(.2)
    port=listener.getsockname()[1];stopped=threading.Event();transports=[];threads=[]
    def handle(client):
        transport=paramiko.Transport(client);transports.append(transport);transport.add_server_key(host_key)
        transport.set_subsystem_handler('sftp',paramiko.SFTPServer,Files)
        try:
            transport.start_server(server=Auth())
            while transport.is_active() and not stopped.wait(.05):pass
        except (EOFError,OSError,paramiko.SSHException):pass
        finally:transport.close()
    def accept():
        while not stopped.is_set():
            try:client,_=listener.accept()
            except socket.timeout:continue
            except OSError:break
            thread=threading.Thread(target=handle,args=(client,),daemon=True);threads.append(thread);thread.start()
    thread=threading.Thread(target=accept,daemon=True);thread.start()
    known=tmp_path/'known_hosts'
    known.write_text(f'[127.0.0.1]:{port} {host_key.get_name()} {host_key.get_base64()}\n')
    password=tmp_path/'password';password.write_text('local-test-password')
    cfg={'host':'127.0.0.1','port':port,'username':'test-user','root':'/objects','known_hosts_file':str(known),'password_file':str(password)}
    yield cfg,root
    stopped.set();listener.close()
    for transport in transports:transport.close()
    thread.join(timeout=2)
    for item in threads:item.join(timeout=2)


def test_real_sftp_upload_stream_rename_delete_and_host_key_rejection(sftp_server,tmp_path):
    cfg,root=sftp_server;store=SFTP(cfg);oid='b'*48
    assert store.check()
    source=tmp_path/'blob';source.write_bytes(b'hello over SFTP')
    store.put(source,oid,15,'digest')
    assert (root/'objects'/oid).read_bytes()==b'hello over SFTP'
    assert not (root/'objects'/(oid+'.part')).exists()
    with store.open(oid,15) as stream:assert stream.read()==b'hello over SFTP'
    store.delete(oid);store.delete(oid)
    assert not (root/'objects'/oid).exists()
    empty=tmp_path/'empty_known_hosts';empty.write_text('')
    with pytest.raises(paramiko.SSHException):SFTP({**cfg,'known_hosts_file':str(empty)}).check()
    wrong=paramiko.RSAKey.generate(2048)
    changed=tmp_path/'changed_known_hosts'
    changed.write_text(f"[127.0.0.1]:{cfg['port']} {wrong.get_name()} {wrong.get_base64()}\n")
    with pytest.raises(paramiko.BadHostKeyException):SFTP({**cfg,'known_hosts_file':str(changed)}).check()
