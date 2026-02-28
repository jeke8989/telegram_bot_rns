"""Static file serving routes — HTML pages, CSS, JS, images."""

from aiohttp import web

routes = web.RouteTableDef()


@routes.get('/')
async def index(request):
    return web.FileResponse('./static/index.html')

@routes.get('/projects')
async def projects_page(request):
    return web.FileResponse('./static/projects.html')

@routes.get('/employees')
async def employees_page(request):
    return web.FileResponse('./static/employees.html')

@routes.get('/proposals')
async def proposals_page(request):
    return web.FileResponse('./static/proposals.html')

@routes.get('/clients')
async def clients_page(request):
    return web.FileResponse('./static/clients.html')

@routes.get('/users')
async def users_page(request):
    return web.FileResponse('./static/users.html')

@routes.get('/seller')
async def seller_page(request):
    return web.FileResponse('./static/seller.html')

@routes.get('/client/{uuid}')
async def client_detail_page(request):
    return web.FileResponse('./static/client.html')

@routes.get('/style.css')
async def css(request):
    return web.FileResponse('./static/style.css')

@routes.get('/script.js')
async def js(request):
    return web.FileResponse('./static/script.js')

@routes.get('/sidebar.js')
async def sidebar_js(request):
    return web.FileResponse('./static/sidebar.js')

@routes.get('/chat-widget.js')
async def chat_widget_js(request):
    return web.FileResponse('./static/chat-widget.js')

@routes.get('/logo.png')
async def logo(request):
    return web.FileResponse('./static/logo.png')

@routes.get('/favicon.ico')
async def favicon(request):
    return web.FileResponse('./static/favicon.ico')

@routes.get('/apple-touch-icon.png')
async def apple_touch_icon(request):
    return web.FileResponse('./static/apple-touch-icon.png')

@routes.get('/og-image.png')
async def og_image(request):
    return web.FileResponse('./static/og-image.png')

@routes.get('/og-meeting.png')
async def og_meeting_image(request):
    return web.FileResponse('./static/og-meeting.png')

@routes.get('/og-meeting.jpg')
async def og_meeting_image_jpg(request):
    return web.FileResponse('./static/og-meeting.jpg')

@routes.get('/og-proposal.png')
async def og_proposal_image(request):
    return web.FileResponse('./static/og-proposal.png')
