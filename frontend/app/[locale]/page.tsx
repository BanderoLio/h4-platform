import { redirect } from 'next/navigation';

type HomePageProps = {
  params: Promise<{ locale: string }>;
};

export default async function Home({ params }: HomePageProps) {
  const { locale } = await params;
  redirect(`/${locale}/repos`);
}
