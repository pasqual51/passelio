import copy
import io
from PIL import Image
from test_app import app,login
from app import create_app
from branding import PRESETS


def image_bytes():
    out=io.BytesIO();Image.new('RGBA',(120,80),'#207090').save(out,format='PNG');return out.getvalue()


def test_raster_upload_activation_persistence_and_removal(app):
    c,h=login(app)
    r=c.post('/api/admin/branding/assets/logo',headers=h,data=image_bytes(),content_type='application/octet-stream')
    assert r.status_code==201
    aid=r.json['id']
    image=c.get('/branding/assets/'+aid)
    assert image.status_code==200 and image.mimetype=='image/png'
    with Image.open(io.BytesIO(image.data)) as decoded:assert decoded.size==(120,80)
    image.close()
    assert c.put('/api/admin/branding',headers=h,json={'logo':aid,'logo_width':100,'theme':'ocean'}).status_code==200
    reopened=create_app(dict(app.config))
    assert reopened.test_client().get('/api/branding').json['logo']==aid
    assert c.delete('/api/admin/branding/assets/'+aid,headers=h).status_code==200
    assert c.get('/api/branding').json['logo'] is None
    assert c.get('/branding/assets/'+aid).status_code==404


def test_branding_authorization_types_and_image_validation(app):
    c,h=login(app)
    assert c.post('/api/admin/branding/assets/logo',data=image_bytes()).status_code==403
    c.post('/api/users',headers=h,json={'email':'user@example.com','password':'member-password-1234'})
    other,oh=login(app,'user@example.com','member-password-1234')
    assert other.get('/api/admin/branding').status_code==403
    assert other.post('/api/admin/branding/assets/logo',headers=oh,data=image_bytes()).status_code==403
    for raw in (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',b'<html>not an image</html>'):
        assert c.post('/api/admin/branding/assets/logo',headers=h,data=raw).status_code==400
    assert c.post('/api/admin/branding/assets/logo',headers=h,data=b'x'*(5*1024**2+1)).status_code==413
    assert c.put('/api/admin/branding',headers=h,json={'logo':'../secret'}).status_code==400
    assert c.put('/api/admin/branding',headers=h,json={'use_backgrounds':True}).status_code==400


def test_data_only_themes_and_contrast(app):
    c,h=login(app)
    theme=copy.deepcopy(PRESETS['ocean']);theme['name']='My ocean'
    assert c.put('/api/admin/branding',headers=h,json={'theme':'custom','custom_theme':theme}).status_code==200
    assert c.get('/api/branding').json['colors']==theme['colors']
    unsafe=copy.deepcopy(theme);unsafe['colors']['primary']='url(javascript:alert(1))'
    assert c.put('/api/admin/branding',headers=h,json={'custom_theme':unsafe}).status_code==400
    low_contrast=copy.deepcopy(theme);low_contrast['colors']['primary']='#ffffff'
    assert c.put('/api/admin/branding',headers=h,json={'custom_theme':low_contrast}).json['error']=='theme_contrast'
    unknown=copy.deepcopy(theme);unknown['css']='body {display:none}'
    assert c.put('/api/admin/branding',headers=h,json={'custom_theme':unknown}).status_code==400


def test_background_selection_and_separate_asset_budget(app):
    c,h=login(app)
    aid=c.post('/api/admin/branding/assets/background',headers=h,data=image_bytes()).json['id']
    assert c.put('/api/admin/branding',headers=h,json={'backgrounds':[aid],'use_backgrounds':True,'rotation_seconds':60}).status_code==200
    assert c.get('/api/branding').json['backgrounds']==[aid]
    assert c.get('/api/shares').json['used']==0
    assert c.put('/api/admin/branding',headers=h,json={'favicon':aid}).status_code==400
    assert c.delete('/api/admin/branding/assets/'+aid,headers=h).status_code==200
    assert not c.get('/api/branding').json['use_backgrounds']
