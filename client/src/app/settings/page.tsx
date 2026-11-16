/**
 * User settings route -- the AI credential, the agent settings and MCP access.
 * @module SettingsPage
 */
import AgentSettings from "@/components/AgentSettings";
import AiSettings from "@/components/AiSettings";
import McpSettings from "@/components/McpSettings";
import { listMcpTokens } from "@/actions/mcpTokens";
import Navbar from "@/components/Navbar";
import GetMyData from "@/api/auth";

/**
 * Server-rendered settings page that fetches the user once and hands the
 * row to the client AiSettings form. The MCP token list is fetched here too
 * and seeds the MCP card.
 *
 * @returns Settings layout with navbar, the BYOK editor, the agent settings
 * and the MCP card.
 */
export default async function Settings() {
  // A failure to list tokens must not take the rest of the settings page down.
  const [user, mcpTokens] = await Promise.all([
    GetMyData(),
    listMcpTokens().catch(() => null),
  ]);

  return (
    <div>
      <Navbar userData={user} />

      <main className="max-w-7xl mx-auto px-6 py-24 flex items-start flex-wrap">
        <header className="flex flex-col md:flex-row justify-between items-start md:items-end gap-6 mb-16">
          <div>
            <h1 className="text-8xl font-extrabold tracking-tight">Settings</h1>
          </div>
        </header>

        <section className="space-y-6 mx-auto max-w-3xl w-full">
          <AiSettings user={user} />
          <AgentSettings user={user} />
          <McpSettings
            initialTokens={mcpTokens ?? []}
            loadFailed={mcpTokens === null}
          />
        </section>
      </main>
    </div>
  );
}
