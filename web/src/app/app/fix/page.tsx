"use client";

import { Suspense } from "react";
import { useQuery } from "../../../nav";
import { Fix } from "../../../screens/Fix";

function Inner() {
  const id = useQuery("job");
  return id ? <Fix jobId={id} /> : <div className="error">No fix loop selected.</div>;
}

export default function Page() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  );
}
