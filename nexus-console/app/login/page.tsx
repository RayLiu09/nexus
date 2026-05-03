export default function LoginPage() {
  return (
    <main className="login-page">
      <section className="login-panel">
        <p className="prototype-id">NX-00</p>
        <h1>NEXUS</h1>
        <p>本地账号入口</p>
        <label>
          账号
          <input name="username" />
        </label>
        <label>
          密码
          <input name="password" type="password" />
        </label>
        <button className="primary-button">进入工作台</button>
      </section>
    </main>
  );
}
