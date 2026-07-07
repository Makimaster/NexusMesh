import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";

import { executionsApi } from "../../api/executions";

export default function ExecutionsPage() {
  const {
    data: executions,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["executions"],
    queryFn: () => executionsApi.list(),
  });

  if (isLoading) return <p>加载中…</p>;
  if (isError) return <p>加载执行列表失败</p>;

  return (
    <div>
      <h1>Executions</h1>
      <ul className="mesh-execution-list">
        {executions?.map((exec) => (
          <li key={exec.id} className="mesh-execution-item">
            <Link to={`/executions/${exec.id}`}>
              <span className="mesh-execution-item__id">{exec.id}</span>
              <span
                className={`mesh-execution-item__status mesh-status--${exec.status}`}
              >
                {exec.status}
              </span>
              <span className="mesh-execution-item__time">
                {exec.created_at}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
