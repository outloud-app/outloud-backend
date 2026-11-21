"""Private watchlist preferences rank candidates; they never bypass quality checks."""
import re
from urllib.parse import urlsplit


def matches(source, follow):
    if source.get('platform') != follow.platform:return False
    if follow.kind=='account':
        parsed=urlsplit(follow.url)
        allowed={'X':{'x.com','twitter.com'},'Instagram':{'instagram.com'},
                 'TikTok':{'tiktok.com'},'Reddit':{'reddit.com'}}
        if (parsed.hostname or '').removeprefix('www.') not in allowed.get(follow.platform,set()):return False
        path=parsed.path.strip('/').split('/')
        if follow.platform=='Reddit':
            if len(path)!=2 or path[0] not in ('user','u'):return False
            handle=path[1]
        else:
            if len(path)!=1:return False
            handle=path[0]
        handle=handle.lstrip('@').casefold()
        if not handle:return False
        author=str(source.get('author','')).lstrip('@').casefold()
        original=urlsplit(source.get('url',''))
        original_host=(original.hostname or '').removeprefix('www.')
        original_path=original.path.strip('/').split('/')
        # Account identity in an original post URL outranks its display name.
        if follow.platform in ('X','TikTok') and original_host in allowed[follow.platform]:
            if original_path and original_path[0].lstrip('@').casefold()==handle:return True
        return author==handle
    wanted=set(re.findall(r'\w+',follow.name.casefold()))
    text=' '.join([source.get('title',''),source.get('summary',''),*source.get('matched_terms',[])])
    return bool(wanted) and wanted <= set(re.findall(r'\w+',text.casefold()))


def score(project, source):
    return sum(matches(source, follow) for follow in getattr(project,'followed_sources',[]))
