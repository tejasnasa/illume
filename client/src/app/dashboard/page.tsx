import { getRepositories } from "@/api/repository";
import Navbar from "@/components/Navbar";
import RepoForm from "@/components/RepoForm";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import MasonryView from "@/components/ui/MasonryView";
import Modal from "@/components/ui/Modal";

const REPO_DATA = [
  {
    id: 1,
    name: "My Repository",
    description: "A simple repository for demonstration purposes.",
    updatedAt: "20 minutes ago",
    github_url: "https://github.com/user/repo1",
    status: "ready",
  },
  {
    id: 2,
    name: "Another Repo",
    description:
      "This is another repository with some sample data fr fr fr fr fr fr fr fr fr fr fr fr fr.",
    updatedAt: "5 days ago",
    github_url: "https://github.com/user/repo2",
    status: "pending",
  },
  {
    id: 3,
    name: "My Repository",
    description:
      "A simple repository for demonstration purposes. lorem ipsum dolor sit amet consectetur adipisicing elit. Voluptas, dicta.",
    updatedAt: "20 minutes ago",
    github_url: "https://github.com/user/repo1",
    status: "ready",
  },
  {
    id: 4,
    name: "Another Repo",
    description:
      "This is another repository with some sample data fr fr fr fr fr fr fr fr fr fr fr fr fr.",
    updatedAt: "5 days ago",
    github_url: "https://github.com/user/repo2",
    status: "pending",
  },
  {
    id: 22,
    name: "Another Repo",
    description:
      "This is another repository with some sample data fr fr fr fr fr fr fr fr fr fr fr fr fr.",
    updatedAt: "5 days ago",
    github_url: "https://github.com/user/repo2",
    status: "pending",
  },
  {
    id: 21,
    name: "Another Repo",
    description:
      "This is another repository with some sample data fr fr fr fr fr fr fr fr fr fr fr fr fr.",
    updatedAt: "5 days ago",
    github_url: "https://github.com/user/repo2",
    status: "pending",
  },
  {
    id: 12,
    name: "Another Repo",
    description:
      "This is another repository with some sample data fr fr fr fr fr fr fr fr fr fr fr fr fr.",
    updatedAt: "5 days ago",
    github_url: "https://github.com/user/repo2",
    status: "pending",
  },
];

export default async function Dashboard() {
  const repositories = await getRepositories();

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

            <RepoForm/>
          </Modal>
        </section>

        <MasonryView repositories={repositories} />
      </main>
    </>
  );
}
