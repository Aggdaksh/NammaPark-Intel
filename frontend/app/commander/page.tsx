import { Suspense } from "react";
import { AppShell } from "../components/AppShell";
import { CommanderClient } from "../components/CommanderClient";

export default function CommanderPage() {
  return (
    <AppShell>
      <Suspense fallback={<div className="notice">Loading command assistant...</div>}>
        <CommanderClient />
      </Suspense>
    </AppShell>
  );
}
