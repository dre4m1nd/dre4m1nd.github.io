---
title: FastAPI 入门到进阶
date: 2026-11-06 12:00:00
description: FastAPI 把 Python 类型注解当成 API 契约：一份声明同时产出校验、序列化、依赖注入和 OpenAPI 文档。这篇覆盖路由与参数、Pydantic v2、Depends 与 yield/scope、鉴权、异步与线程池、lifespan、错误处理、工程结构、测试，以及 0.115~0.162 这一年的新特性和踩坑。
categories:
  - 技术
tags:
  - Python
  - FastAPI
  - 后端
  - Web 框架
cover: /img/2026/11/cover-fastapi-py.jpg
---

## 1. FastAPI 是什么

FastAPI 是 Python 的现代 Web 框架，站在两个库肩上：**Starlette 管 Web 部分（ASGI、路由、中间件），Pydantic 管数据部分（校验、序列化）**。它的核心思路只有一句：**把类型注解当契约，一次声明，四处受益**。

```python
@app.get("/items/{item_id}")
async def read_item(item_id: int) -> Item:
    ...
```

上面这三行类型信息，FastAPI 会同时用来做：

1. **请求解析**：`item_id` 从路径取，转成 `int`，转不动就 422
2. **校验**：返回类型按 `Item` 校验/裁剪，多余的字段不会漏给客户端
3. **依赖注入**：参数里声明 `Depends(x)`，框架负责调用并复用
4. **文档**：自动生成 OpenAPI（`/openapi.json`）+ Swagger UI（`/docs`）+ ReDoc（`/redoc`）

对比一下同位置的几个选择：

| | FastAPI | Flask | Django REST Framework | Fastify（Node） |
| --- | --- | --- | --- | --- |
| 校验 | **Pydantic 模型** | 自己写 / 扩展 | Serializer | JSON Schema |
| 文档 | **自动 OpenAPI** | 需扩展 | 需 drf-spectacular | 自动 OpenAPI |
| 异步 | **原生 async** | 支持 | 有限 | async-first |
| 依赖注入 | **内置 Depends** | 无 | 无（有 View 层） | 装饰器/钩子 |
| 类型提示 | **核心机制** | 无 | 部分 | TS 类型 |
| 全家桶 | 否（自带足够） | 否 | **是**（ORM/Admin/迁移） | 否 |

一句话选型：**要"类型安全 + 自动文档 + 异步"的 API 服务，选 FastAPI；要 Admin/ORM/全家桶的中后台，Django 仍然更省事。**

## 2. 环境与起步

### 2.1. 装什么

FastAPI 要求 **Python ≥ 3.10**（0.162 的 `requires_python`）。官方推荐用 `uv` 管项目，用 pip 也行：

```bash
# uv（推荐）
uv init awesome-api --bare
cd awesome-api
uv add "fastapi[standard]"

# 或者 pip + venv
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install "fastapi[standard]"
```

`[standard]` 这一串不是可有可无的便利包，它装的东西基本就是你上线要用的全部：

| 包 | 作用 |
| --- | --- |
| `uvicorn[standard]` | ASGI 服务器（含 uvloop/httptools） |
| `fastapi-cli` | `fastapi dev` / `fastapi run` 命令 |
| `httpx` | 测试用 `TestClient` 的底层 |
| `python-multipart` | 表单 / 文件上传 |
| `email-validator` | `EmailStr` 校验 |
| `pydantic-settings` | 环境变量配置 |
| `jinja2` | 模板渲染 |
| `opentelemetry-sdk` + `otlp-proto-http` | 0.142 起内置的 OTel 遥测 |

### 2.2. 最小可运行

```python
# main.py
from typing import Annotated
from fastapi import FastAPI, Path
from pydantic import BaseModel

app = FastAPI(title="Awesome API")

class Item(BaseModel):
    name: str
    price: float

@app.get("/")
async def root():
    return {"hello": "world"}

@app.get("/items/{item_id}")
async def read_item(item_id: Annotated[int, Path(ge=1)], q: str | None = None):
    return {"item_id": item_id, "q": q}

@app.post("/items/", status_code=201)
async def create_item(item: Item):
    return item
```

跑起来：

```bash
fastapi dev main.py     # 开发：127.0.0.1:8000 + 自动重载
fastapi run main.py     # 生产：0.0.0.0:8000，无重载
```

两个命令的区别值得记住，它们不只是"加不加 --reload"：

| | `fastapi dev` | `fastapi run` |
| --- | --- | --- |
| 监听地址 | `127.0.0.1`（只有本机能连） | `0.0.0.0`（容器/公网可达） |
| 自动重载 | 开 | 关 |
| `FASTAPI_ENV` | 设成 `development`（已存在则不覆盖） | 不动 |
| 用途 | 本机开发 | 生产/容器 |

然后三个端点全都能访问：`/docs`（Swagger UI，可直接点"Try it out"发请求）、`/redoc`、`/openapi.json`。**这就是"类型注解即文档"最直观的收益**——接口改一行注解，文档自动跟着变，不用维护第二份 yaml。

> 容器里跑 `fastapi dev` 会连不上：它只绑 `127.0.0.1`。要调试就用 `fastapi dev --host 0.0.0.0` 或直接 `uvicorn main:app --host 0.0.0.0`。

## 3. 参数从哪来：一条判断规则

FastAPI 的参数来源判定很简单，记住这张表就不会猜错：

| 参数写法 | 来源 |
| --- | --- |
| 名字出现在路径模板里（`/items/{id}`） | 路径参数 |
| 类型是 Pydantic 模型（`item: Item`） | 请求体 JSON |
| 基本类型（`int` / `str` / `bool` / `list[str]`…）且不在路径里 | 查询参数 |
| `Annotated[X, Query()]` / `Path()` / `Header()` / `Cookie()` / `Form()` / `File()` | 强制指定来源 |

```python
from typing import Annotated
from fastapi import FastAPI, Query, Header, Cookie, Form

@app.get("/search")
async def search(
    q: Annotated[str | None, Query(min_length=2, max_length=50)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    tags: Annotated[list[str], Query()] = [],
    user_agent: Annotated[str | None, Header()] = None,
    session: Annotated[str | None, Cookie()] = None,
):
    return {"q": q, "limit": limit, "tags": tags, "ua": user_agent, "s": session}
```

`?tags=a&tags=b` 会解析成 `["a", "b"]`；`Header()` 默认把下划线转成中划线（`user_agent` → `User-Agent`），不想转就 `Header(convert_underscores=False)`。

### 3.1. 参数模型：一组查询参数收进一个类

参数多起来时，别再往函数签名里堆。用 Pydantic 模型 + `Query()`（**0.115 起支持**）：

```python
from typing import Annotated, Literal
from fastapi import FastAPI, Query
from pydantic import BaseModel, Field, ConfigDict

class FilterParams(BaseModel):
    model_config = ConfigDict(extra="forbid")     # 未知查询键直接报错
    limit: int = Field(10, ge=1, le=50)
    offset: int = Field(0, ge=0)
    order_by: Literal["created_at", "updated_at"] = "created_at"

@app.get("/items/")
async def list_items(f: Annotated[FilterParams, Query()]):
    return f
```

`?limit=3&order_by=price` → `{"limit":3,"offset":0,"order_by":"price"}`；`?order_by=price` 之外的值 → 422；`?limt=5`（拼错）→ 422（因为 `extra="forbid"`）。

`Header()` / `Cookie()` / `Form()` 也支持同样的模型写法：查询/头/Cookie 模型 0.115 一起上的，表单模型更早（0.113）。2026 年补的是**多个模型组合**——0.157 支持 query/header/cookie 模型合并，0.161 支持 form 模型合并。

**注意 `extra` 的作用范围（0.160 变更）**：模型的 `extra` 配置现在作用于**同一位置上的所有字段**，包括兄弟参数和依赖里声明的字段。所以 `extra="forbid"` 的查询模型会把函数里另一个 `q: str | None` 也一起管住：

```python
class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_by: str = "name"

@app.get("/sibling")
def sibling(f: Annotated[Filter, Query()], q: str | None = None): ...
# GET /sibling?order_by=x&q=hello  → 422 extra_forbidden: q
```

这是 0.160 的破坏性变更，升级时要检查"同一位置既有 forbid 模型、又有裸参数"的端点。

## 4. Pydantic v2：校验的实际用法

FastAPI 0.100 之后全面转向 Pydantic v2，写法有几处和 v1 不同（`model_config` 取代 `class Config`、`model_validate` 取代 `parse_obj`）。日常最常用的三件事：

```python
from pydantic import BaseModel, Field, ConfigDict, EmailStr

class UserIn(BaseModel):
    model_config = ConfigDict(extra="forbid")        # 拒绝多余字段
    email: EmailStr                                  # 需要 email-validator（standard 已带）
    name: str = Field(min_length=1, max_length=20)
    age: int | None = Field(default=None, ge=0, le=150)

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # 允许从对象属性读（ORM 对象直接返回）
    id: int
    email: str
```

### 4.1. 输入模型和输出模型分开

**永远不要把"能写入的字段"和"能读出的字段"用同一个模型**。分开写有三个实际好处：

1. 密码、内部字段不会被误返回（不是靠人记着删）
2. 出参可以加 `from_attributes`，直接返回 ORM 对象
3. `response_model` 会做一次**过滤 + 校验**，模型外的字段直接消失

```python
@app.get("/items/{item_id}", response_model=ItemOut)
async def read_item(item_id: int):
    return {"id": item_id, "name": "x", "price": 1.0, "secret": "leak"}
# 实际返回 {"id":1,"name":"x","price":1.0} —— secret 被裁掉了
```

这个行为值得亲手验证一次：`response_model` 不是"提示"，是真的会把多出来的字段丢掉。

### 4.2. 校验失败长什么样

422 的响应体结构固定，前端可以直接按 `loc` 定位到字段：

```json
{"detail": [{"type": "string_too_long", "loc": ["query", "q"],
             "msg": "String should have at most 10 characters", "input": "aaaaaaaaaaaaaaaaaaaa"}]}
```

`loc` 的第一段就是位置（`path` / `query` / `header` / `cookie` / `body`）。头模型的报错在 0.152 起会显示 HTTP 头名（`x-tag`）而不是 Python 字段名（`x_tag`）。

## 5. 依赖注入：Depends

`Depends` 是 FastAPI 区别于 Flask 的最大一块。它解决的问题是：**"多个端点都要做的准备动作，怎么写成可复用、可测试、能自动清理的东西"**。

```python
from typing import Annotated
from fastapi import Depends, FastAPI, Query

app = FastAPI()

def pagination(limit: Annotated[int, Query(ge=1, le=100)] = 20,
               offset: Annotated[int, Query(ge=0)] = 0) -> dict:
    return {"limit": limit, "offset": offset}

@app.get("/users")
async def list_users(p: Annotated[dict, Depends(pagination)]):
    return p
```

### 5.1. 带 yield 的依赖：资源必须还回去

数据库会话、文件句柄、锁——这些东西的正确写法是 `yield`：

```python
async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session            # 出了这个块，session 一定被关
```

### 5.2. `scope="function"`：提前释放（0.121 新增）

默认行为（`scope="request"`）是：**响应发完之后**才执行 `yield` 后面的清理代码。这对 `StreamingResponse` 是必须的（流还没发完，会话不能关），但对"只在依赖里用一次数据库"的场景就白白占着连接。

0.121 加了 `scope` 参数：

```python
from fastapi import Depends

@app.get("/users/me")
def me(username: Annotated[str, Depends(get_username, scope="function")]):
    return username
```

| `scope` | 清理时机 | 适合 |
| --- | --- | --- |
| `"request"`（默认） | 响应发送**之后** | 会话要给流式响应、后台任务用 |
| `"function"` | 端点函数返回**之后、响应发送之前** | 依赖内部用完即弃的资源 |

实测的执行顺序（`fn` 用 `scope="function"`，`req` 用默认）：

```text
fn-open → req-open → handler → fn-close → bg-task → req-close
```

规则：**`scope="request"` 的依赖，其子依赖也必须是 `"request"`；`"function"` 可以套 `"request"`。** 因为外层的清理代码可能要引用子依赖的返回值，清理顺序必须是"后进先出"。

### 5.3. 类依赖

把参数组写成类，`Depends()` 不传参时会自动读 `__init__` 的签名：

```python
class Paginator:
    def __init__(self, limit: Annotated[int, Query(ge=1, le=100)] = 20,
                 offset: Annotated[int, Query(ge=0)] = 0):
        self.limit, self.offset = limit, offset
    def slice(self, items): return items[self.offset:self.offset + self.limit]

@app.get("/list")
def lst(p: Annotated[Paginator, Depends()]):
    return p.slice(list(range(10)))
# GET /list?limit=3&offset=2 → [2, 3, 4]
```

### 5.4. 复用、缓存与覆盖

- **同一请求内默认复用**：一个依赖被多个参数/多个依赖声明时，只调用一次（`use_cache=True`）。想每次都重新算就 `Depends(dep, use_cache=False)`。
- **路由级依赖**：`APIRouter(dependencies=[Depends(verify_token)])`，整组端点统一加校验，不用每个函数都写一遍。
- **测试覆盖**：`app.dependency_overrides[get_db] = lambda: fake_db`。这是 FastAPI 测试最有用的一招——替换外部依赖，不用 monkeypatch。

```python
app.dependency_overrides[get_config] = lambda: "test"   # 测试里
```

## 6. 鉴权：三种常见写法

| 需求 | 方案 | 缺凭证时返回 |
| --- | --- | --- |
| 自定义头 / Bearer token | `HTTPBearer()` | **401 Not authenticated** |
| OAuth2 密码流 | `OAuth2PasswordBearer(tokenUrl="token")` | 401（并写进 OpenAPI 安全方案） |
| 普通必需头 | `Annotated[str, Header()]` | **422 缺字段**（不是 401） |

```python
from typing import Annotated
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

app = FastAPI()
oauth2 = OAuth2PasswordBearer(tokenUrl="token")

def current_user(token: Annotated[str, Depends(oauth2)]) -> str:
    if token != "abc":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token",
                            headers={"WWW-Authenticate": "Bearer"})
    return "alice"

@app.get("/me")
def me(user: Annotated[str, Depends(current_user)]):
    return {"user": user}
```

`OAuth2PasswordBearer` 会把自己写进 OpenAPI 的 `securitySchemes`，所以 `/docs` 右上角会出现 **Authorize** 按钮——点一下填 token，之后所有请求自动带头。**这个按钮不是装饰，是安全方案声明带来的。**

## 7. 异步、线程池，以及最容易踩的那个坑

FastAPI 对 `def` 和 `async def` 的处理不一样：

| 写法 | 执行方式 | 什么时候用 |
| --- | --- | --- |
| `async def` | 直接在事件循环里跑 | 用 `await` 的库（asyncpg/httpx/aiofiles…） |
| `def` | 丢到线程池（`anyio.to_thread`） | 用同步库（requests、psycopg2、Pillow…） |

**线程池默认只有 40 个 token**（Starlette 的 `anyio` 默认限额），而且和 FastAPI 跑同步依赖共享。这意味着：

- 同步端点一多，并发上限就是 40 个线程——不是"慢"，是排队
- 在 `async def` 里写 `requests.get()` 或 `time.sleep()` 会**卡住整个事件循环**，所有请求一起等

```python
# ❌ 灾难：async 端点里做阻塞调用
@app.get("/bad")
async def bad():
    return requests.get("https://api.example.com").json()

# ✅ 有 await 就用 async 库
@app.get("/good")
async def good():
    async with httpx.AsyncClient() as c:
        r = await c.get("https://api.example.com")
    return r.json()

# ✅ 同步库就老老实实写 def，让它进线程池
@app.get("/also-ok")
def also_ok():
    return requests.get("https://api.example.com").json()
```

要调线程池容量（比如同步端点确实很多）：

```python
import anyio.to_thread
limiter = anyio.to_thread.current_default_thread_limiter()
limiter.total_tokens = 100      # 默认 40
```

调大会有内存开销，先量再调。

## 8. lifespan：启动和关闭

**Starlette 1.0（2026-03）在自己的 API 上删掉了 `on_startup` / `on_shutdown` / `@app.on_event`**。FastAPI 在应用层保留了兼容层（`app.on_event` 会发 DeprecationWarning，`on_startup=` 参数仍能传），但新代码统一用 `lifespan`：

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：建连接池、跑迁移检查（create_pool 换成你自己的工厂）
    app.state.pool = await create_pool()
    yield                                   # ← 应用在这中间对外服务
    # 关闭：释放资源
    await app.state.pool.close()

app = FastAPI(lifespan=lifespan)
```

`yield` 出来的字典会进 `app.state`（Starlette 0.26+ 的 lifespan state），两种写法等价——自己赋值 `app.state.x`，或者直接 yield 一个字典：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield {"pool": "fake-pool"}             # 键会自动进 app.state

@app.get("/state")
def state(request: Request):
    return {"pool": request.state.pool}      # {'pool': 'fake-pool'}
```

## 9. 中间件与 CORS

中间件是"包在路由外面"的一层，比依赖更靠外（请求进来先过中间件，再解析参数、跑依赖）：

```python
@app.middleware("http")
async def add_process_time(request: Request, call_next):
    response = await call_next(request)
    response.headers["x-extra"] = "1"
    return response
```

跨域（前端和 API 不同源时必备）：

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app.example.com"],   # 别用 ["*"] + credentials
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## 10. 错误处理

```python
from fastapi import HTTPException, status, Request
from fastapi.responses import JSONResponse

@app.get("/teapot")
def teapot():
    raise HTTPException(418, detail="teapot")     # → 418 {"detail":"teapot"}

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
```

两个细节：

- **`raise HTTPException` 和 `return` 是一回事，别都写**——抛了异常就不会再 return
- 想统一错误体（比如 `{"error": ..., "code": ...}`），用 `@app.exception_handler` 覆盖；422 的校验错误要覆盖得处理 `RequestValidationError`

## 11. 工程结构：从单文件到能维护

单文件写到两三百行就该拆了。一个够用的结构：

```text
app/
├── main.py              # FastAPI() 实例 + include_router + 中间件 + lifespan
├── config.py            # pydantic-settings 读环境变量
├── deps.py              # get_db / current_user 等公共依赖
├── models.py            # SQLAlchemy 模型
├── schemas.py           # Pydantic 入参/出参模型
└── routers/
    ├── users.py
    └── items.py
```

```python
# app/routers/items.py
from typing import Annotated
from fastapi import APIRouter, Depends
from ..deps import current_user
from ..schemas import ItemOut

router = APIRouter(prefix="/items", tags=["items"],
                   dependencies=[Depends(current_user)])   # 整组要登录

@router.get("/", response_model=list[ItemOut])
async def list_items(): ...

# app/main.py
from fastapi import FastAPI
from .routers import items, users

app = FastAPI()
app.include_router(items.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
```

配置用 `pydantic-settings`（`standard` 已装），环境变量自动映射、类型自动转换：

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_")
    db_url: str = "sqlite+aiosqlite:///./dev.db"
    debug: bool = False

settings = Settings()
# APP_DB_URL=... APP_DEBUG=true 会被自动读到
```

## 12. 数据库：异步 SQLAlchemy 的最小闭环

FastAPI 官方教程用的是 SQLAlchemy。异步版的关键是三个东西：`create_async_engine`、`async_sessionmaker`、`expire_on_commit=False`。

```python
from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator
from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase): pass

class Todo(Base):
    __tablename__ = "todo"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]

engine = create_async_engine("sqlite+aiosqlite:///:memory:")
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(lifespan=lifespan)

async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as s:
        yield s

class TodoIn(BaseModel):
    title: str

class TodoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str

@app.post("/todos", response_model=TodoOut, status_code=201)
async def create(t: TodoIn, db: Annotated[AsyncSession, Depends(get_db)]):
    todo = Todo(title=t.title)
    db.add(todo)
    await db.commit()
    await db.refresh(todo)          # 拿回自增 id
    return todo                     # from_attributes 让 ORM 对象直接能返回

@app.get("/todos", response_model=list[TodoOut])
async def list_todos(db: Annotated[AsyncSession, Depends(get_db)]):
    res = await db.execute(select(Todo))
    return list(res.scalars())
```

三个容易忘的点：`expire_on_commit=False`（否则 commit 后属性会失效，序列化时触发 lazy load 报错）、`await db.refresh()`（要自增 id）、`from_attributes=True`（不然不能直接返回 ORM 对象）。

## 13. 测试

同步用 `TestClient`（底层是 httpx），异步用 `httpx.AsyncClient` + `ASGITransport`：

```python
# 同步
from fastapi.testclient import TestClient
from app.main import app

def test_read():
    c = TestClient(app)
    r = c.get("/items/7?q=abc")
    assert r.status_code == 200
    assert r.json() == {"id": 7, "name": "abc", "price": 1.0}

# 异步
import httpx, pytest, asyncio
from app.main import app

@pytest.mark.asyncio
async def test_async_read():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/items/7?q=abc")
    assert r.status_code == 200
```

`TestClient` 作为上下文管理器（`with TestClient(app) as c:`）时会真的跑 `lifespan`——这是测启动逻辑（建表、建连接池）的唯一正确姿势。

依赖替换在测试里是这样用的：

```python
def test_override():
    app.dependency_overrides[get_config] = lambda: "test"
    assert TestClient(app).get("/cfg").json() == {"cfg": "test"}
    app.dependency_overrides.clear()
```

## 14. 可观测性：内置 OpenTelemetry（0.142+）

FastAPI 从 **0.142.0（2026-09-29）** 起**原生支持 OpenTelemetry**，不用再装 `opentelemetry-instrumentation-fastapi`：装上 `fastapi[standard]` 就有 SDK 和 OTLP/HTTP 导出器，框架自己给每个请求打 span（还有 `fastapi.dependencies` / `fastapi.endpoint` / `fastapi.serialization` 这些细粒度 span）。

**0.143.0（2026-10-08）把这个改成了 opt-in**：默认不会自动从 `OTEL_*` 环境变量建导出器，要显式开：

```bash
export FASTAPI_OTEL_AUTO_CONFIGURE=true
export OTEL_SERVICE_NAME=my-api
export OTEL_EXPORTER_OTLP_ENDPOINT=https://collector.example.com   # HTTP/protobuf 基地址
fastapi run main.py
```

或者代码里配：

```python
app = FastAPI(telemetry={"tracing": True, "auto_configure": True})
```

`telemetry` 字典能控的开关：

| 键 | 作用 | 默认 |
| --- | --- | --- |
| `tracing` / `metrics` / `logs` | 记不记 span / 指标 / 校验失败与未处理异常 | `True` |
| `operation_spans` | 是否加依赖/端点/序列化的子 span | `True` |
| `exclude` | 传 ASGI scope，返回 `True` 的请求跳过 | `None` |
| `auto_configure` | 是否按环境变量加 OTLP 导出器 | 看 `FASTAPI_OTEL_AUTO_CONFIGURE` |

**这里有个真实踩过的坑**：`auto_configure` 变 opt-in 了，但 `tracing` 默认还是 `True`，而 FastAPI 会复用**已存在的全局 tracer provider**。如果你的项目已经用别的库（比如 LLM 观测的 Phoenix）注册了全局 provider，升级到 0.142 后你的观测后台会突然涌进一堆 API span。两种解法：

```python
app = FastAPI(telemetry={"tracing": False})         # 关掉 FastAPI 自己的遥测
# 或者注册时不要设全局 provider（set_global_tracer_provider=False）
```

另外两个坑：自动配置只支持 **OTLP/HTTP**（`OTEL_EXPORTER_OTLP_PROTOCOL=grpc` 会启动报错、静默不发数据）；健康检查端点记得用 `exclude` 排除，不然 trace 里全是 `/health`。

## 15. 部署

最小可用的容器跑法：

```bash
# 生产：多进程，不带 reload
fastapi run main.py --host 0.0.0.0 --port 8000 --workers 4
# 等价于 uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

对应的 Dockerfile（多阶段不必须，重点是 `[standard]` 和 `--host 0.0.0.0`）：

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
# 容器里监听 0.0.0.0，workers 数按 CPU 核数定，通常 2*核数+1
CMD ["fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

```text
# requirements.txt
fastapi[standard]==0.162.0
```

要点：

- **不再需要 gunicorn**。以前"gunicorn + uvicorn worker"的组合是为了多进程，现在 `uvicorn --workers` / `fastapi run --workers` 就够了
- `--proxy-headers`（默认开）配合 `--forwarded-allow-ips` 才能拿到真实的客户端 IP 和 `https` 协议
- 容器里必须 `--host 0.0.0.0`，`127.0.0.1` 在容器内等于不可达
- HTTPS 交给前面的反向代理（Nginx / 云负载均衡）终止
- **版本要 pin**：FastAPI 是 `0.x`，语义化版本下 minor 版本就可能破坏兼容。`fastapi[standard]==0.162.0`，别让它自己漂
- Starlette 别自己 pin，让 FastAPI 决定

健康检查端点（顺带把它从遥测里排除）：

```python
@app.get("/health")
async def health():
    return {"ok": True}
```

## 16. 易错点清单

- **`Annotated` 是唯一推荐写法**：`q: Annotated[str, Query(...)] = None`。老的 `q: str = Query(None, ...)` 还能用，但默认值和校验混在一个调用里，容易写反
- **0.155 起 `Query(custom="x")` 会 `TypeError`**：`Path/Query/Header/Cookie/Body/Form/File` 的 `**extra` 被删了，额外的 JSON Schema 属性要写 `json_schema_extra={"custom": "x"}`
- **`extra="forbid"` 的模型会管到同位置的所有字段**（0.160），兄弟参数和依赖里的字段也会被拒
- **`response_model` 是真的会裁字段**，不是文档；反过来，不加 `response_model` 就等于把 ORM 对象原样吐出去（可能带内部字段）
- **`async def` 里不要做阻塞调用**：一次 `requests.get()` 卡住的是整个事件循环，不是单个请求
- **同步端点默认只有 40 线程额度**，和同步依赖共享；同步端点多了要调 `anyio` 的 `total_tokens`
- **`Depends(scope="function")` 的子依赖必须是 `request` 或 `function`**，反过来不行
- **`yield` 依赖的清理默认在响应发送之后**；返回 `StreamingResponse` 时这是必须的，但只在依赖内用资源就该用 `scope="function"` 早点还
- **必填的 bool 表单字段**：0.162 起没传就 422（以前会被悄悄填成 `False`）。HTML 复选框要写成 `Annotated[bool, Form()] = False`
- **表单和 JSON 不能混**：`Form()` 意味着 `multipart/form-data` 或 `x-www-form-urlencoded`，再声明 `Body` 字段会 422
- **缺鉴权头返回 401，缺普通必需头返回 422**——不是 bug，是 `HTTPBearer`/`OAuth2PasswordBearer` 和 `Header()` 的语义差异
- **`@app.on_event` 已被 Starlette 1.0 删除**，FastAPI 只是留了带警告的兼容层，新代码用 `lifespan`
- **`TestClient` 不进 `with` 就不会跑 lifespan**，测启动逻辑时容易误判
- **藏文档要显式关**：`docs_url=None` 只关 Swagger UI（`/openapi.json` 还在），`openapi_url=None` 才是文档和 schema 一起消失

## 17. 重点总结

- **一次类型声明，四处收益**：解析、校验、依赖注入、OpenAPI。这是 FastAPI 的全部卖点，也是它的约束——**类型写得含糊，框架就帮不了你**
- **参数来源只看类型和注解**：路径里的名字 → 路径；Pydantic 模型 → body；基本类型 → query；`Annotated[X, Query()/Header()/Form()]` 强制指定
- **输入模型和输出模型必须分开**，出参加 `response_model` 让框架真的裁字段
- **依赖注入是主力抽象**：`yield` 管资源，`scope="function"` 提前释放，`dependencies=[...]` 挂在 router 上做整组鉴权，测试用 `dependency_overrides` 换实现
- **`async def` 配 async 库，`def` 配同步库**，混着来会卡事件循环或撞线程池上限（默认 40）
- **生命周期统一用 `lifespan`**，`on_event` 已被上游删除
- **`fastapi dev` 是 127.0.0.1 + reload，`fastapi run` 是 0.0.0.0 + 无 reload**，容器里别用 dev
- **值得记住的新东西**：参数模型（0.113 表单 / 0.115 query+header+cookie，0.157/0.161 支持多模型合并）、`Depends(scope=...)`（0.121）、内置 OpenTelemetry（0.142，0.143 起 auto_configure 需 opt-in）、`**extra` 移除（0.155）、`extra` 作用范围扩大（0.160）、必填 bool 表单（0.162）
- **pin 版本**：`0.x` 的 minor 就可能破坏兼容，升级靠测试兜底

## 18. 参考

- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [FastAPI 发布说明（release notes）](https://fastapi.tiangolo.com/release-notes/)
- [FastAPI CLI](https://fastapi.tiangolo.com/fastapi-cli/)
- [依赖注入与 `yield` / `scope`](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/)
- [查询参数模型](https://fastapi.tiangolo.com/tutorial/query-param-models/)
- [表单模型](https://fastapi.tiangolo.com/tutorial/request-form-models/)
- [OpenTelemetry（内置遥测）](https://fastapi.tiangolo.com/advanced/opentelemetry/)
- [并发 async / await](https://fastapi.tiangolo.com/async/)
- [Starlette Thread Pool（40 token 上限）](https://starlette.dev/threadpool/)
- [Starlette 1.0 发布说明（移除 on_event）](https://starlette.dev/release-notes/)
</content>
</write>
