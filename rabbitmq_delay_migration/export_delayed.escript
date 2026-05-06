#!/usr/bin/env escript
%%! -noshell

-module(export_delayed).
-export([main/1]).

-define(PROPERTY_FIELDS, [
    content_type,
    content_encoding,
    headers,
    delivery_mode,
    priority,
    correlation_id,
    reply_to,
    expiration,
    message_id,
    timestamp,
    type,
    user_id,
    app_id,
    cluster_id
]).

main(Args) ->
    application:ensure_all_started(crypto),
    case parse_args(Args) of
        {ok, Opts} ->
            try run(Opts) of
                ok ->
                    ok;
                {error, Reason} ->
                    fail(Reason)
            catch
                throw:Reason ->
                    fail(Reason);
                error:Reason ->
                    fail({unexpected_error, Reason})
            end;
        {error, Reason} ->
            usage(Reason),
            halt(1)
    end.

run(Opts) ->
    Node = maps:get(node, Opts),
    Cookie = maps:get(cookie, Opts),
    Output = maps:get(output, Opts),
    VhostFilter = maps:get(vhost, Opts),
    case start_distribution(Node, Cookie) of
        ok ->
            try
                ensure_remote_plugin(Node),
                Table = rpc_call(Node, rabbit_delayed_message, table_name, []),
                IndexTable = rpc_call(Node, rabbit_delayed_message, index_table_name, []),
                {ok, Fd} = file:open(Output, [write, binary, raw, {delayed_write, 65536, 250}]),
                try
                    FirstKey = rpc_call(Node, mnesia, dirty_first, [IndexTable]),
                    Count = export_loop(Node, Table, IndexTable, FirstKey, Fd, VhostFilter, 0),
                    io:format("Exported ~B delayed messages to ~s~n", [Count, Output]),
                    ok
                after
                    file:close(Fd)
                end
            after
                stop_distribution()
            end;
        {error, _} = Error ->
            Error
    end.

parse_args(Args) ->
    parse_args(Args, #{vhost => all}).

parse_args([], Opts) ->
    Required = [node, cookie, output],
    case [Key || Key <- Required, not maps:is_key(Key, Opts)] of
        [] ->
            {ok, Opts};
        Missing ->
            {error, io_lib:format("missing required arguments: ~s", [string:join([atom_to_list(K) || K <- Missing], ", ")])}
    end;
parse_args(["--node", Value | Rest], Opts) ->
    parse_args(Rest, Opts#{node => list_to_atom(Value)});
parse_args(["--cookie", Value | Rest], Opts) ->
    parse_args(Rest, Opts#{cookie => Value});
parse_args(["--output", Value | Rest], Opts) ->
    parse_args(Rest, Opts#{output => Value});
parse_args(["--vhost", "all" | Rest], Opts) ->
    parse_args(Rest, Opts#{vhost => all});
parse_args(["--vhost", Value | Rest], Opts) ->
    parse_args(Rest, Opts#{vhost => list_to_binary(Value)});
parse_args(["--help" | _], _Opts) ->
    {error, help_requested};
parse_args([Unknown | _], _Opts) ->
    {error, io_lib:format("unknown argument: ~s", [Unknown])}.

usage(help_requested) ->
    usage("export delayed messages from rabbitmq delayed plugin storage");
usage(Reason) ->
    io:format(
        standard_error,
        "Usage: export_delayed.escript --node rabbit@host --cookie COOKIE --output /tmp/messages.jsonl [--vhost all|VHOST]~n~ts~n",
        [to_list(Reason)]
    ).

fail(Reason) ->
    io:format(standard_error, "ERROR: ~ts~n", [format_error(Reason)]),
    halt(1).

format_error({cannot_connect, Node}) ->
    io_lib:format("cannot connect to remote RabbitMQ node ~p", [Node]);
format_error({module_not_loaded, Module, Path}) ->
    io_lib:format("remote module ~p is not available: ~p", [Module, Path]);
format_error({badrpc, Reason}) ->
    io_lib:format("rpc call failed: ~p", [Reason]);
format_error({unsupported_delivery_shape, Snippet}) ->
    io_lib:format("unsupported delayed message shape, sample term: ~ts", [Snippet]);
format_error({invalid_delay_entry, Entry}) ->
    io_lib:format("unexpected delayed entry structure: ~ts", [safe_term_snippet(Entry)]);
format_error({unexpected_error, Reason}) ->
    io_lib:format("unexpected runtime error: ~p", [Reason]);
format_error(Reason) ->
    io_lib:format("~p", [Reason]).

start_distribution(RemoteNode, CookieString) ->
    NameType = name_type(RemoteNode),
    LocalName = list_to_atom("delay_export_" ++ integer_to_list(erlang:unique_integer([positive]))),
    case net_kernel:start([LocalName, NameType]) of
        {ok, _Pid} ->
            true = erlang:set_cookie(node(), list_to_atom(CookieString)),
            case net_adm:ping(RemoteNode) of
                pong -> ok;
                pang -> {error, {cannot_connect, RemoteNode}}
            end;
        {error, Reason} ->
            {error, Reason}
    end.

stop_distribution() ->
    catch net_kernel:stop(),
    ok.

name_type(Node) ->
    NodeText = atom_to_list(Node),
    case string:split(NodeText, "@", all) of
        [_Name, Host] ->
            case lists:member($., Host) of
                true -> longnames;
                false -> shortnames
            end;
        _ ->
            shortnames
    end.

ensure_remote_plugin(Node) ->
    Path = rpc_call(Node, code, which, [rabbit_delayed_message]),
    case Path of
        non_existing ->
            throw({module_not_loaded, rabbit_delayed_message, Path});
        _ ->
            ok
    end.

export_loop(_Node, _Table, _IndexTable, '$end_of_table', _Fd, _VhostFilter, Count) ->
    Count;
export_loop(Node, Table, IndexTable, Key, Fd, VhostFilter, Count) ->
    Deliveries = rpc_call(Node, mnesia, dirty_read, [Table, Key]),
    NewCount = lists:foldl(
        fun (Entry, Acc) ->
            case maybe_export_entry(Entry, Fd, VhostFilter) of
                skip -> Acc;
                ok -> Acc + 1
            end
        end,
        Count,
        Deliveries
    ),
    maybe_log_progress(NewCount),
    NextKey = rpc_call(Node, mnesia, dirty_next, [IndexTable, Key]),
    export_loop(Node, Table, IndexTable, NextKey, Fd, VhostFilter, NewCount).

maybe_log_progress(Count) when Count > 0, Count rem 1000 =:= 0 ->
    io:format("Exported ~B messages...~n", [Count]);
maybe_log_progress(_Count) ->
    ok.

maybe_export_entry(Entry, Fd, VhostFilter) ->
    Exported = build_export_record(Entry),
    case matches_vhost(VhostFilter, maps:get(vhost, Exported)) of
        true ->
            Line = encode_json(Exported),
            ok = file:write(Fd, [Line, <<"\n">>]),
            ok;
        false ->
            skip
    end.

matches_vhost(all, _Vhost) ->
    true;
matches_vhost(Expected, Actual) ->
    Expected =:= Actual.

build_export_record({delay_entry, {delay_key, DueAtMs, Exchange}, Delivery, _Ref}) ->
    {Vhost, ExchangeName} = extract_exchange_ref(Exchange),
    {RoutingKey, Headers, Properties, PayloadBase64} = extract_delivery_payload(Delivery),
    MsgId = build_msg_id(Vhost, ExchangeName, RoutingKey, DueAtMs, Headers, Properties, PayloadBase64),
    #{
        msg_id => MsgId,
        vhost => binary_to_text(Vhost),
        exchange => binary_to_text(ExchangeName),
        routing_key => binary_to_text(RoutingKey),
        due_at_ms => DueAtMs,
        headers => Headers,
        properties => Properties,
        payload_base64 => PayloadBase64
    };
build_export_record(Entry) ->
    throw({invalid_delay_entry, Entry}).

extract_exchange_ref({exchange, NameResource, _Type, _Durable, _AutoDelete, _Internal, _Arguments, _Scratches, _Policy, _OperatorPolicy, _Decorators, _Options}) ->
    extract_resource(NameResource);
extract_exchange_ref({exchange, NameResource, _Type, _Durable, _AutoDelete, _Internal, _Arguments, _Scratches, _Policy, _Decorators}) ->
    extract_resource(NameResource);
extract_exchange_ref(Exchange) ->
    throw({unsupported_delivery_shape, safe_term_snippet(Exchange)}).

extract_resource({resource, Vhost, _Kind, Name}) ->
    {ensure_binary(Vhost), ensure_binary(Name)};
extract_resource(Resource) ->
    throw({unsupported_delivery_shape, safe_term_snippet(Resource)}).

extract_delivery_payload({delivery, _Mandatory, _Confirm, _Sender, Message, _MsgSeqNo, _Flow}) ->
    extract_basic_message(Message);
extract_delivery_payload({basic_message, _ExchangeName, _RoutingKeys, _Content, _Id, _Persistent} = Message) ->
    extract_basic_message(Message);
extract_delivery_payload(Unknown) ->
    throw({unsupported_delivery_shape, safe_term_snippet(Unknown)}).

extract_basic_message({basic_message, _ExchangeName, RoutingKeys, Content, _Id, _Persistent}) ->
    RoutingKey = first_routing_key(RoutingKeys),
    {Headers, Properties, PayloadBase64} = extract_content(Content),
    {RoutingKey, Headers, Properties, PayloadBase64};
extract_basic_message(Unknown) ->
    throw({unsupported_delivery_shape, safe_term_snippet(Unknown)}).

first_routing_key([RoutingKey | _]) ->
    ensure_binary(RoutingKey);
first_routing_key([]) ->
    <<>>;
first_routing_key(Value) ->
    ensure_binary(Value).

extract_content({content, _ClassId, Props, _PropsBin, _Protocol, PayloadFragmentsRev}) ->
    Payload = iolist_to_binary(lists:reverse(PayloadFragmentsRev)),
    Headers = normalize_headers(extract_headers(Props)),
    Properties = normalize_properties(Props),
    {Headers, Properties, base64:encode(Payload)};
extract_content(Unknown) ->
    throw({unsupported_delivery_shape, safe_term_snippet(Unknown)}).

extract_headers({'P_basic', _ContentType, _ContentEncoding, Headers, _DeliveryMode, _Priority, _CorrelationId, _ReplyTo, _Expiration, _MessageId, _Timestamp, _Type, _UserId, _AppId, _ClusterId}) ->
    Headers;
extract_headers(_) ->
    undefined.

normalize_properties({'P_basic' = _Tag, ContentType, ContentEncoding, _Headers, DeliveryMode, Priority, CorrelationId, ReplyTo, Expiration, MessageId, Timestamp, Type, UserId, AppId, ClusterId}) ->
    Raw = [
        {content_type, ContentType},
        {content_encoding, ContentEncoding},
        {delivery_mode, DeliveryMode},
        {priority, Priority},
        {correlation_id, CorrelationId},
        {reply_to, ReplyTo},
        {expiration, Expiration},
        {message_id, MessageId},
        {timestamp, Timestamp},
        {type, Type},
        {user_id, UserId},
        {app_id, AppId},
        {cluster_id, ClusterId}
    ],
    lists:foldl(
        fun ({_Key, undefined}, Acc) ->
            Acc;
            ({Key, Value}, Acc) ->
                Acc#{Key => normalize_property_value(Key, Value)}
        end,
        #{},
        Raw
    );
normalize_properties(_Other) ->
    #{}.

normalize_property_value(timestamp, Value) ->
    Value;
normalize_property_value(delivery_mode, Value) ->
    Value;
normalize_property_value(priority, Value) ->
    Value;
normalize_property_value(_Key, Value) ->
    maybe_binary_text(Value).

normalize_headers(undefined) ->
    #{};
normalize_headers([]) ->
    #{};
normalize_headers(Headers) when is_list(Headers) ->
    lists:foldl(
        fun ({Key, Type, Value}, Acc) ->
            Acc#{binary_to_text(ensure_binary(Key)) => #{
                amqp_type => atom_to_binary(Type, utf8),
                value => normalize_amqp_value(Type, Value)
            }};
            (Other, _Acc) ->
                throw({unsupported_delivery_shape, safe_term_snippet(Other)})
        end,
        #{},
        Headers
    );
normalize_headers(Other) ->
    throw({unsupported_delivery_shape, safe_term_snippet(Other)}).

normalize_amqp_value(table, Entries) when is_list(Entries) ->
    lists:foldl(
        fun ({Key, Type, Value}, Acc) ->
            Acc#{binary_to_text(ensure_binary(Key)) => #{
                amqp_type => atom_to_binary(Type, utf8),
                value => normalize_amqp_value(Type, Value)
            }};
            (Other, _Acc) ->
                throw({unsupported_delivery_shape, safe_term_snippet(Other)})
        end,
        #{},
        Entries
    );
normalize_amqp_value(array, Values) when is_list(Values) ->
    [normalize_array_item(Item) || Item <- Values];
normalize_amqp_value(longstr, Value) ->
    maybe_binary_text(Value);
normalize_amqp_value(shortstr, Value) ->
    maybe_binary_text(Value);
normalize_amqp_value(bytearray, Value) ->
    binary_blob(Value);
normalize_amqp_value(timestamp, Value) ->
    Value;
normalize_amqp_value(decimal, {Scale, Number}) ->
    #{
        scale => Scale,
        value => Number
    };
normalize_amqp_value(void, _Value) ->
    null;
normalize_amqp_value(_Type, Value) when is_integer(Value); is_float(Value); is_boolean(Value) ->
    Value;
normalize_amqp_value(_Type, Value) when is_binary(Value) ->
    maybe_binary_text(Value);
normalize_amqp_value(Type, Value) ->
    #{
        amqp_fallback_type => atom_to_binary(Type, utf8),
        erlang_term_base64 => base64:encode(term_to_binary(Value))
    }.

normalize_array_item({Type, Value}) ->
    #{
        amqp_type => atom_to_binary(Type, utf8),
        value => normalize_amqp_value(Type, Value)
    };
normalize_array_item(Value) ->
    #{
        amqp_type => <<"longstr">>,
        value => normalize_amqp_value(longstr, Value)
    }.

maybe_binary_text(Value) when is_binary(Value) ->
    try unicode:characters_to_binary(Value, utf8, utf8) of
        Converted when is_binary(Converted) ->
            binary_to_text(Converted)
    catch
        _:_ ->
            binary_blob(Value)
    end;
maybe_binary_text(Value) when is_list(Value) ->
    unicode:characters_to_binary(Value);
maybe_binary_text(Value) ->
    Value.

binary_blob(Value) ->
    #{
        encoding => <<"base64">>,
        data => base64:encode(ensure_binary(Value))
    }.

build_msg_id(Vhost, Exchange, RoutingKey, DueAtMs, Headers, Properties, PayloadBase64) ->
    Digest = crypto:hash(
        sha256,
        term_to_binary({Vhost, Exchange, RoutingKey, DueAtMs, Headers, Properties, PayloadBase64})
    ),
    hex_encode(Digest).

hex_encode(Bin) ->
    list_to_binary(lists:flatten([io_lib:format("~2.16.0b", [Byte]) || <<Byte>> <= Bin])).

rpc_call(Node, Mod, Fun, Args) ->
    case rpc:call(Node, Mod, Fun, Args) of
        {badrpc, Reason} ->
            throw({badrpc, Reason});
        Result ->
            Result
    end.

ensure_binary(Value) when is_binary(Value) ->
    Value;
ensure_binary(Value) when is_atom(Value) ->
    atom_to_binary(Value, utf8);
ensure_binary(Value) when is_list(Value) ->
    unicode:characters_to_binary(Value);
ensure_binary(Value) ->
    unicode:characters_to_binary(io_lib:format("~p", [Value])).

binary_to_text(Value) when is_binary(Value) ->
    Value.

safe_term_snippet(Term) ->
    List = lists:flatten(io_lib:format("~p", [Term])),
    case length(List) > 240 of
        true -> lists:sublist(List, 240) ++ "...";
        false -> List
    end.

encode_json(Value) ->
    iolist_to_binary(json_encode(Value)).

json_encode(Map) when is_map(Map) ->
    Pairs = lists:sort(
        fun ({K1, _}, {K2, _}) ->
            key_to_list(K1) =< key_to_list(K2)
        end,
        maps:to_list(Map)
    ),
    EncodedPairs = [
        [json_encode_string(key_to_binary(Key)), $:, json_encode(Val)]
        || {Key, Val} <- Pairs
    ],
    [$\{, join_with_commas(EncodedPairs), $\}];
json_encode(List) when is_list(List) ->
    [$[, join_with_commas([json_encode(Item) || Item <- List]), $]];
json_encode(Bin) when is_binary(Bin) ->
    json_encode_string(Bin);
json_encode(Int) when is_integer(Int) ->
    integer_to_list(Int);
json_encode(Float) when is_float(Float) ->
    float_to_list(Float, [compact]);
json_encode(true) ->
    <<"true">>;
json_encode(false) ->
    <<"false">>;
json_encode(null) ->
    <<"null">>;
json_encode(undefined) ->
    <<"null">>;
json_encode(Atom) when is_atom(Atom) ->
    json_encode_string(atom_to_binary(Atom, utf8));
json_encode(Other) ->
    json_encode_string(ensure_binary(Other)).

join_with_commas([]) ->
    [];
join_with_commas([Only]) ->
    Only;
join_with_commas([Head | Tail]) ->
    [Head, [[$,, Item] || Item <- Tail]].

json_encode_string(Bin) ->
    Escaped = lists:flatten([escape_json_char(C) || C <- unicode:characters_to_list(Bin, utf8)]),
    [$", Escaped, $"].

escape_json_char($") -> "\\\"";
escape_json_char($\\) -> "\\\\";
escape_json_char($\b) -> "\\b";
escape_json_char($\f) -> "\\f";
escape_json_char($\n) -> "\\n";
escape_json_char($\r) -> "\\r";
escape_json_char($\t) -> "\\t";
escape_json_char(C) when C < 16#20 ->
    io_lib:format("\\u~4.16.0B", [C]);
escape_json_char(C) ->
    [C].

key_to_binary(Key) when is_binary(Key) ->
    Key;
key_to_binary(Key) when is_atom(Key) ->
    atom_to_binary(Key, utf8);
key_to_binary(Key) when is_list(Key) ->
    unicode:characters_to_binary(Key);
key_to_binary(Key) ->
    ensure_binary(Key).

key_to_list(Key) ->
    unicode:characters_to_list(key_to_binary(Key)).

to_list(Value) when is_list(Value) ->
    Value;
to_list(Value) when is_binary(Value) ->
    unicode:characters_to_list(Value);
to_list(Value) ->
    lists:flatten(io_lib:format("~p", [Value])).
