"use client";

import { Suspense } from "react";
import { useQuery } from "../../../nav";
import { RunView } from "../../../screens/RunView";

function Inner() {
  const id = useQuery("id");
  const episode = useQuery("episode") ?? undefined;
  return id ? <RunView runId={id} episodeId={episode} /> : <div className="error">No run selected.</div>;
}

export default function Page() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  );
}
