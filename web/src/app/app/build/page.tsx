"use client";

import { Suspense } from "react";
import { useQuery } from "../../../nav";
import { Build } from "../../../screens/Build";

function Inner() {
  const id = useQuery("id");
  return id ? <Build jobId={id} /> : <div className="error">No build selected.</div>;
}

export default function Page() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  );
}
