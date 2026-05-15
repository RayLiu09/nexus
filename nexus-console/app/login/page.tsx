export default function LoginPage() {
  return (
    <main className="login-page">
      <section className="login-panel">
        <p className="page-header-badge">NX-00</p>
        <h1>NEXUS</h1>
        <p className="login-subtitle">企业数据与知识资产平台</p>
        <label>
          账号
          <input name="username" placeholder="输入用户名" />
        </label>
        <label>
          密码
          <input name="password" type="password" placeholder="输入密码" />
        </label>
        <div className="login-actions">
          <button className="btn btn-primary btn-lg">进入工作台</button>
          <button className="btn btn-ghost btn-sm">本地账号入口</button>
        </div>
      </section>
    </main>
  );
}
