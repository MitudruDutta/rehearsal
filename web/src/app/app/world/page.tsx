"use client";

import { Suspense } from "react";
import { useQuery } from "../../../nav";
import { World } from "../../../screens/World";

function Inner() {
  const id = useQuery("id");
  return id ? <World worldVersionId={id} /> : <div className="error">No world version selected.</div>;
}

export default function Page() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  );
}
