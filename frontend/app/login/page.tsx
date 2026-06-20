import { Suspense } from "react";
import { LoginClient } from "../components/LoginClient";

export default function LoginPage() {
  return (
    <Suspense fallback={<main className="login-screen"><section className="login-card">Loading login...</section></main>}>
      <LoginClient />
    </Suspense>
  );
}
