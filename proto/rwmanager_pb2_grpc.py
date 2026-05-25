# Generated protocol buffer gRPC helpers, trimmed to the methods used here.

import grpc

import proto.rwmanager_pb2 as proto_dot_rwmanager__pb2


class RwManagerStub:
    def __init__(self, channel):
        self.GetUserByUsername = channel.unary_unary(
            "/rwmanager.RwManager/GetUserByUsername",
            request_serializer=proto_dot_rwmanager__pb2.GetUserByUsernameRequest.SerializeToString,
            response_deserializer=proto_dot_rwmanager__pb2.UserResponse.FromString,
        )
        self.UpdateUser = channel.unary_unary(
            "/rwmanager.RwManager/UpdateUser",
            request_serializer=proto_dot_rwmanager__pb2.UpdateUserRequest.SerializeToString,
            response_deserializer=proto_dot_rwmanager__pb2.UserResponse.FromString,
        )
        self.GetAllUsers = channel.unary_unary(
            "/rwmanager.RwManager/GetAllUsers",
            request_serializer=proto_dot_rwmanager__pb2.GetAllUsersRequest.SerializeToString,
            response_deserializer=proto_dot_rwmanager__pb2.GetAllUsersReply.FromString,
        )
