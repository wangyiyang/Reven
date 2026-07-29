require "socket"

port = File.read(".attack-port").to_i
[
  ["127.0.0.1", port],
  ["169.254.169.254", 80],
].each do |host, target_port|
  begin
    Socket.tcp(host, target_port, connect_timeout: 0.2).close
    raise "sandbox network escaped to #{host}"
  rescue Errno::ECONNREFUSED, Errno::ENETUNREACH, Errno::EHOSTUNREACH, Errno::ETIMEDOUT
    nil
  end
end

raise "sandbox exposed /data" if File.exist?("/data/secret")
