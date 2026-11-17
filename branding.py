"""Validated visual assets and data-only themes. No uploaded HTML/SVG/CSS."""
import io
import json
import re
import secrets
import shutil
import time
import warnings
from pathlib import Path

from flask import jsonify,request,send_file
from PIL import Image,ImageOps,UnidentifiedImageError


PRESETS={
 'midnight':dict(name='Midnight',colors=dict(primary='#101c32',accent='#087a66',background='#f3f6f8')),
 'ocean':dict(name='Ocean',colors=dict(primary='#153b66',accent='#176b82',background='#f1f7fb')),
 'amber':dict(name='Amber',colors=dict(primary='#442c26',accent='#9a4e12',background='#fbf7f0'))
}


def contrast(a,b):
    def luminance(value):
        values=[int(value[i:i+2],16)/255 for i in (1,3,5)]
        return sum(v*w for v,w in zip([v/12.92 if v<=0.04045 else ((v+0.055)/1.055)**2.4 for v in values],(.2126,.7152,.0722)))
    x,y=sorted([luminance(a),luminance(b)])
    return (y+.05)/(x+.05)


def validate_theme(theme):
    if not isinstance(theme,dict) or set(theme)!={'name','colors'}:raise ValueError('invalid_theme')
    if not isinstance(theme['name'],str) or not 1<=len(theme['name'])<=60 or any(ord(x)<32 for x in theme['name']):raise ValueError('invalid_theme')
    colors=theme['colors']
    if not isinstance(colors,dict) or set(colors)!={'primary','accent','background'} or any(not isinstance(c,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',c) for c in colors.values()):raise ValueError('invalid_theme')
    if min(contrast(colors['primary'],'#ffffff'),contrast(colors['accent'],'#ffffff'),contrast(colors['background'],'#18243a'),contrast(colors['primary'],colors['background']),contrast(colors['accent'],colors['background']))<4.5:raise ValueError('theme_contrast')
    return dict(name=theme['name'],colors={k:v.lower() for k,v in colors.items()})


def init_branding(app,db,root,protected,fail,audit):
    assets=Path(root)/'branding';assets.mkdir(exist_ok=True)
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS branding_config(id INTEGER PRIMARY KEY CHECK(id=1),value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS branding_assets(id TEXT PRIMARY KEY,kind TEXT NOT NULL,size INTEGER NOT NULL,
         width INTEGER NOT NULL,height INTEGER NOT NULL,created INTEGER NOT NULL);
        ''')

    def config(c=None):
        if c is None:
            with db() as connection:return config(connection)
        default=dict(logo=None,favicon=None,logo_width=42,use_backgrounds=False,backgrounds=[],rotation_seconds=180,
                     show_powered=True,theme='midnight',custom_theme=None)
        row=c.execute('SELECT value FROM branding_config WHERE id=1').fetchone()
        if row:default.update(json.loads(row['value']))
        return default

    def write(c,value):
        c.execute('INSERT INTO branding_config VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value',(json.dumps(value),))

    @app.get('/api/branding')
    def public_branding():
        value=config()
        value['colors']=(value['custom_theme'] if value['theme']=='custom' else PRESETS[value['theme']])['colors']
        return jsonify(value)

    @app.get('/api/admin/branding')
    @protected(admin=True)
    def admin_branding():
        with db() as c:
            value=config(c)
            items=[dict(r) for r in c.execute('SELECT * FROM branding_assets ORDER BY created DESC,id')]
        return jsonify(settings=value,assets=items,presets=PRESETS)

    @app.put('/api/admin/branding')
    @protected(admin=True)
    def save_branding():
        body=request.get_json(silent=True) or {}
        with db(True) as c:
            old=config(c)
            if not body or set(body)-set(old):return fail('invalid_input')
            value={**old,**body}
            if type(value['logo_width']) is not int or not 24<=value['logo_width']<=180 or type(value['rotation_seconds']) is not int or value['rotation_seconds'] not in (0,60,180,300,600,1800):return fail('invalid_input')
            if any(type(value[k]) is not bool for k in ('use_backgrounds','show_powered')):return fail('invalid_input')
            if not isinstance(value['backgrounds'],list) or len(value['backgrounds'])>8 or any(not isinstance(v,str) for v in value['backgrounds']):return fail('invalid_input')
            value['backgrounds']=list(dict.fromkeys(value['backgrounds']))
            for kind,ids in [('logo',[value['logo']]),('favicon',[value['favicon']]),('background',value['backgrounds'])]:
                for aid in ids:
                    if aid is not None and (not isinstance(aid,str) or not c.execute('SELECT 1 FROM branding_assets WHERE id=? AND kind=?',(aid,kind)).fetchone()):return fail('invalid_input')
            if value['theme'] not in (*PRESETS,'custom'):return fail('invalid_theme')
            if value['custom_theme'] is not None:
                try:value['custom_theme']=validate_theme(value['custom_theme'])
                except ValueError as e:return fail(str(e))
            if value['theme']=='custom' and value['custom_theme'] is None:return fail('invalid_theme')
            if value['use_backgrounds'] and not value['backgrounds']:return fail('branding_background_required')
            write(c,value);audit(c,'branding.updated')
        return jsonify(ok=True)

    @app.post('/api/admin/branding/assets/<kind>')
    @protected(admin=True)
    def upload_asset(kind):
        if kind not in ('logo','favicon','background'):return fail('invalid_input')
        if not request.content_length or request.content_length>5*1024**2:return fail('image_too_large',413)
        try:
            raw=request.get_data()
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as opened:
                    if opened.format not in ('PNG','JPEG','WEBP') or opened.width*opened.height>20_000_000 or getattr(opened,'n_frames',1)!=1:raise ValueError()
                    opened.load()
                    image=ImageOps.exif_transpose(opened).convert('RGBA')
                    maximum=256 if kind=='favicon' else 1024 if kind=='logo' else 2560
                    image.thumbnail((maximum,maximum))
                    # A new image strips EXIF, comments, embedded profiles and metadata.
                    clean=Image.new('RGBA',image.size);clean.paste(image)
                    out=io.BytesIO();clean.save(out,format='PNG');data=out.getvalue()
        except (ValueError,OSError,UnidentifiedImageError,Image.DecompressionBombWarning,Image.DecompressionBombError):return fail('invalid_image')
        if len(data)>8*1024**2:return fail('image_too_large',413)
        aid=secrets.token_hex(24)
        with db(True) as c:
            count=c.execute('SELECT count(*) FROM branding_assets').fetchone()[0]
            used=c.execute('SELECT coalesce(sum(size),0) FROM branding_assets').fetchone()[0]
            if count>=12 or used+len(data)>32*1024**2 or shutil.disk_usage(root).free<len(data)+64*1024**2:return fail('branding_quota',413)
            path=assets/(aid+'.png')
            try:
                path.write_bytes(data)
                c.execute('INSERT INTO branding_assets VALUES(?,?,?,?,?,?)',(aid,kind,len(data),clean.width,clean.height,int(time.time())))
                audit(c,'branding.asset_uploaded',aid)
            except Exception:
                path.unlink(missing_ok=True)
                raise
        return jsonify(id=aid,width=clean.width,height=clean.height,size=len(data)),201

    @app.delete('/api/admin/branding/assets/<aid>')
    @protected(admin=True)
    def remove_asset(aid):
        with db(True) as c:
            if not c.execute('SELECT 1 FROM branding_assets WHERE id=?',(aid,)).fetchone():return fail('not_found',404)
            value=config(c)
            for key in ('logo','favicon'):
                if value[key]==aid:value[key]=None
            value['backgrounds']=[v for v in value['backgrounds'] if v!=aid]
            if not value['backgrounds']:value['use_backgrounds']=False
            write(c,value)
            c.execute('DELETE FROM branding_assets WHERE id=?',(aid,))
            # Only server-generated IDs from the table can reach this path.
            (assets/(aid+'.png')).unlink(missing_ok=True)
            audit(c,'branding.asset_removed',aid)
        return jsonify(ok=True)

    @app.get('/branding/assets/<aid>')
    def image_asset(aid):
        if not re.fullmatch(r'[a-f0-9]{48}',aid):return fail('not_found',404)
        with db() as c:
            if not c.execute('SELECT 1 FROM branding_assets WHERE id=?',(aid,)).fetchone():return fail('not_found',404)
        return send_file(assets/(aid+'.png'),mimetype='image/png',conditional=True)
