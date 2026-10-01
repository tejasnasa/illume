/**
 * User settings route -- AI credentials editor lives here today.
 * @module SettingsPage
 */
import AiSettings from "@/components/AiSettings";
import Navbar from "@/components/Navbar";
import GetMyData from "@/api/auth";

/**
 * Server-rendered settings page that fetches the user once and hands the
 * row to the client AiSettings form.
 *
 * @returns Settings layout with navbar and the BYOK editor.
 */
export default async function Settings() {
  const user = await GetMyData();

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
        </section>
      </main>
    </div>
  );
}
