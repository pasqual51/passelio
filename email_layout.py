"""Constrained email HTML, escaped substitutions and shared bilingual layout."""
import html
from html.parser import HTMLParser
import re
from string import Template
from urllib.parse import urlsplit


class EmailHTML(HTMLParser):
    tags={'p','br','strong','em','b','i','u','ul','ol','li','h1','h2','h3','a','table','tbody','thead','tr','td','th','blockquote','hr','span','div'}
    void={'br','hr'}
    blocked={'script','style','iframe','object','embed','svg','math','form','textarea','head'}
    def __init__(self):super().__init__(convert_charrefs=True);self.output=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in self.blocked:self.skip+=1;return
        if self.skip or tag not in self.tags:return
        kept=[]
        for name,value in attrs:
            if tag=='a' and name=='href' and value:
                value=value.strip()
                if not any(ord(c)<32 for c in value) and urlsplit(value).scheme.lower() in ('http','https','mailto'):
                    kept.append('href="'+html.escape(value,quote=True)+'"')
            elif name=='title' and value:kept.append('title="'+html.escape(value,quote=True)+'"')
        if tag=='a':kept+=['rel="noopener noreferrer"','target="_blank"']
        self.output.append('<'+tag+(' '+' '.join(kept) if kept else '')+'>')
    def handle_endtag(self,tag):
        if tag in self.blocked:
            self.skip=max(0,self.skip-1);return
        if not self.skip and tag in self.tags and tag not in self.void:self.output.append('</'+tag+'>')
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.void:self.handle_endtag(tag)
    def handle_data(self,data):
        if not self.skip:self.output.append(html.escape(data))


def sanitize(source):
    parser=EmailHTML();parser.feed(source);parser.close();return ''.join(parser.output)


def render(template,values,application_name,language='en'):
    escaped={key:html.escape(str(value),quote=True) for key,value in values.items()}
    body=sanitize(Template(template.get('html','')).substitute(escaped)) if template.get('html') else ''.join('<p>'+html.escape(line)+'</p>' for line in Template(template['body']).substitute(values).splitlines() if line)
    heading=html.escape(Template(template.get('heading') or template['subject']).substitute(values))
    label=template.get('button') or ('Ouvrir le lien' if language=='fr' else 'Open link')
    url=values.get('url','')
    button=('<p><a style="display:inline-block;padding:12px 20px;border-radius:8px;background:#087a66;color:#fff;text-decoration:none" href="'+html.escape(url,quote=True)+'">'+html.escape(label)+'</a></p>') if urlsplit(url).scheme in ('http','https') else ''
    return '<!doctype html><html><body style="font-family:Arial,sans-serif;background:#f3f6f8;padding:24px;color:#18243a"><main style="max-width:640px;margin:auto;background:white;padding:28px;border-radius:12px"><p>'+html.escape(application_name)+'</p><h1>'+heading+'</h1>'+body+button+'<hr><p>'+html.escape(template.get('footer',''))+'</p></main></body></html>'


def validate_fields(body):
    if set(body)-{'subject','body','html','heading','button','footer'} or not {'subject','body'}<=set(body):return False
    for name,limit in [('subject',200),('body',10000),('html',20000),('heading',200),('button',80),('footer',500)]:
        value=body.get(name,'')
        if not isinstance(value,str) or len(value)>limit or '\r' in value or (name!='body' and name!='html' and '\n' in value):return False
        try:Template(value).substitute(title='Example',url='https://example.invalid/',expiry='Date',sender='sender@example.invalid')
        except (KeyError,ValueError):return False
    return bool(body['subject'].strip() and body['body'].strip())
