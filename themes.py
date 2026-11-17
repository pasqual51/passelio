"""Data-only theme palettes. Erugo-derived palettes: see third_party notices."""
import json
from pathlib import Path

OPTIONAL_COLORS={'surface','text','muted','subtle','border','primary_text','primary_end','background_end'}


def luminance(value):
    values=[int(value[i:i+2],16)/255 for i in (1,3,5)]
    return sum(v*w for v,w in zip([v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values],(.2126,.7152,.0722)))


def contrast(a,b):
    x,y=sorted([luminance(a),luminance(b)])
    return (y+.05)/(x+.05)


def mix(color,target,amount):
    return '#'+''.join(f'{round(int(color[i:i+2],16)*(1-amount)+int(target[i:i+2],16)*amount):02x}' for i in (1,3,5))


def fit(color,backgrounds):
    for step in range(101):
        candidates=[mix(color,target,step/100) for target in ('#000000','#ffffff')]
        for candidate in candidates:
            if min(contrast(candidate,bg) for bg in backgrounds)>=4.5:return candidate
    raise ValueError('theme_contrast')


def palette(colors):
    dark=luminance(colors['background'])<.2
    result=dict(surface='#ffffff',text='#18243a',muted='#637385',subtle='#f5f8fa',border='#dce4e9',primary_text='#ffffff')
    if dark:result.update(surface=colors['background'],text='#f4f6fb',muted='#bec7d6',subtle=colors['background'],border='#526078')
    result.update(colors)
    return result


def validate_palette(colors):
    p=palette(colors)
    surfaces=[p['background'],p.get('background_end',p['background']),p['surface'],p['subtle']]
    pairs=[(p[k],b) for k in ('text','muted','accent') for b in surfaces]
    pairs += [(p['primary_text'],p[k]) for k in ('primary','primary_end') if k in p]
    return all(contrast(a,b)>=4.5 for a,b in pairs)


def reference_presets():
    rows=json.loads((Path(__file__).parent/'third_party/erugo-theme-reference.json').read_text(encoding='utf-8'))
    result={}
    for row in rows:
        c=dict(row['colors'])
        for key in ('primary','primary_end'):
            if key in c:c[key]=fit(c[key],[c['primary_text']])
        surfaces=[c['background'],c.get('background_end',c['background']),c['surface'],c['subtle']]
        for key in ('text','muted','accent'):c[key]=fit(c[key],surfaces)
        key='erugo-'+''.join(ch.lower() if ch.isalnum() else '-' for ch in row['name']).strip('-')
        result[key]=dict(name=row['name'],colors=c)
    return result
