"use client";

import { Suspense } from "react";
import { useQuery } from "../../../nav";
import { CliLogin } from "../../../screens/CliLogin";

function Inner() {
  const code = useQuery("code");
  return <CliLogin code={code || ""} />;
}

export default function Page() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  );
}
