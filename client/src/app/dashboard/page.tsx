import Navbar from "@/components/Navbar";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Modal from "@/components/ui/Modal";

export default function Dashboard() {
  return (
    <>
      <Navbar />
      <main className="mx-28">
        <section className="flex justify-between items-end mt-24">
          <h1 className="text-8xl">Dashboard</h1>
          <Modal trigger={<Button className="m-4">+ Add New Repo</Button>}>
            <h2 className="text-2xl font-semibold text-center">
              Add New Repository
            </h2>

            <form className="flex flex-col mt-6 gap-2 ">
              <label
                htmlFor="url"
                className="text-sm text-(--muted-foreground)"
              >
                Repository URL
              </label>
              <Input
                className="w-full"
                id="url"
                placeholder="https://github.com/user/repo"
              />

              <Button className="self-end mt-2" size="sm">
                Add Repository
              </Button>
            </form>
          </Modal>
        </section>
      </main>
    </>
  );
}
